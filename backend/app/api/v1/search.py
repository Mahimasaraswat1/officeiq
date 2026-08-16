"""Global search across employees, documents, tasks and the knowledge base
(PRD A.9).

This is *navigational* search — a fast way to jump to a record you already know
exists. It matches literal substrings, case-insensitively, and deliberately does
not use embeddings: `POST /knowledge/search` is the semantic path, and quietly
returning conceptually-similar-but-differently-named records here would make the
jump-to box unpredictable.

Results are role-scoped at the query level, not filtered afterwards, so an
employee's search can never load rows they are not allowed to see.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, DbSession
from app.models.document import Document
from app.models.employee import Employee
from app.models.enums import UserRole
from app.models.knowledge import KnowledgeDocument
from app.models.task import EmployeeTask
from app.models.user import User
from app.schemas.search import SearchGroup, SearchHit, SearchResults

router = APIRouter(prefix="/search", tags=["Search"])


def _like(term: str) -> str:
    # Escape the LIKE wildcards so a literal % or _ in the query matches itself.
    escaped = term.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _employee_scope(db: Session, user: User) -> Employee | None:
    """The employee record a non-HR user is allowed to see: their own."""
    return db.scalar(select(Employee).where(Employee.user_id == user.id))


def _group(
    db: Session, kind: str, label: str, stmt, count_stmt, limit: int, to_hit
) -> SearchGroup:
    total = db.scalar(count_stmt) or 0
    rows = db.execute(stmt.limit(limit)).all()
    return SearchGroup(
        kind=kind, label=label, total=total, items=[to_hit(row) for row in rows]
    )


@router.get("", response_model=SearchResults, summary="Search across the workspace")
def search(
    db: DbSession,
    user: CurrentUser,
    q: Annotated[str, Query(min_length=2, description="At least two characters")],
    limit: Annotated[int, Query(ge=1, le=25)] = 5,
) -> SearchResults:
    term = _like(q)
    is_hr = user.role in (UserRole.ADMIN, UserRole.HR)
    groups: list[SearchGroup] = []

    if is_hr:
        employee_match = or_(
            func.lower(Employee.first_name).like(term, escape="\\"),
            func.lower(Employee.last_name).like(term, escape="\\"),
            func.lower(Employee.first_name + " " + Employee.last_name).like(term, escape="\\"),
            func.lower(Employee.employee_code).like(term, escape="\\"),
            func.lower(Employee.work_email).like(term, escape="\\"),
            func.lower(Employee.department).like(term, escape="\\"),
            func.lower(Employee.designation).like(term, escape="\\"),
        )
        groups.append(
            _group(
                db,
                "employee",
                "Employees",
                select(Employee).where(employee_match).order_by(Employee.first_name),
                select(func.count()).select_from(Employee).where(employee_match),
                limit,
                lambda row: SearchHit(
                    kind="employee",
                    id=str(row[0].id),
                    title=row[0].full_name,
                    subtitle=f"{row[0].employee_code} · {row[0].department or 'No department'}",
                    badge=row[0].onboarding_status.value,
                    link=f"/employees/{row[0].id}",
                ),
            )
        )

    # --- Documents ---------------------------------------------------------
    document_match = func.lower(Document.original_filename).like(term, escape="\\")
    document_filters = [document_match]
    scope = None
    if not is_hr:
        scope = _employee_scope(db, user)
        if scope is None:
            # No employee record means no documents and no tasks to search.
            document_filters.append(Document.id.is_(None))
        else:
            document_filters.append(Document.employee_id == scope.id)

    groups.append(
        _group(
            db,
            "document",
            "Documents",
            select(Document, Employee)
            .join(Employee, Document.employee_id == Employee.id)
            .where(*document_filters)
            .order_by(Document.created_at.desc()),
            select(func.count()).select_from(Document).where(*document_filters),
            limit,
            lambda row: SearchHit(
                kind="document",
                id=str(row[0].id),
                title=row[0].original_filename,
                subtitle=f"{row[0].document_type.value} · {row[1].full_name}",
                badge=row[0].status.value,
                link=(
                    f"/employees/{row[1].id}" if is_hr else "/my-onboarding"
                ),
            ),
        )
    )

    # --- Tasks -------------------------------------------------------------
    task_match = func.lower(EmployeeTask.title).like(term, escape="\\")
    task_filters = [task_match]
    if not is_hr:
        if scope is None:
            task_filters.append(EmployeeTask.id.is_(None))
        else:
            task_filters.append(EmployeeTask.employee_id == scope.id)

    groups.append(
        _group(
            db,
            "task",
            "Tasks",
            select(EmployeeTask, Employee)
            .join(Employee, EmployeeTask.employee_id == Employee.id)
            .where(*task_filters)
            .order_by(EmployeeTask.due_date.is_(None), EmployeeTask.due_date),
            select(func.count()).select_from(EmployeeTask).where(*task_filters),
            limit,
            lambda row: SearchHit(
                kind="task",
                id=str(row[0].id),
                title=row[0].title,
                subtitle=(
                    f"{row[0].category.value} · {row[1].full_name}"
                    if is_hr
                    else row[0].category.value
                ),
                badge=row[0].status.value,
                link=f"/employees/{row[1].id}" if is_hr else "/my-tasks",
            ),
        )
    )

    # --- Knowledge base ----------------------------------------------------
    # Employees only reach published handbook content; HR also sees drafts,
    # which is the whole point of a draft.
    knowledge_match = or_(
        func.lower(KnowledgeDocument.title).like(term, escape="\\"),
        func.lower(KnowledgeDocument.content).like(term, escape="\\"),
    )
    knowledge_filters = [knowledge_match]
    if not is_hr:
        knowledge_filters.append(KnowledgeDocument.is_published.is_(True))

    groups.append(
        _group(
            db,
            "knowledge",
            "Knowledge base",
            select(KnowledgeDocument)
            .where(*knowledge_filters)
            .order_by(KnowledgeDocument.title),
            select(func.count()).select_from(KnowledgeDocument).where(*knowledge_filters),
            limit,
            lambda row: SearchHit(
                kind="knowledge",
                id=str(row[0].id),
                title=row[0].title,
                subtitle=row[0].category.value,
                badge=None if row[0].is_published else "draft",
                link="/knowledge-base" if is_hr else "/assistant",
            ),
        )
    )

    return SearchResults(
        query=q,
        total=sum(group.total for group in groups),
        groups=groups,
        limit_per_group=limit,
    )
