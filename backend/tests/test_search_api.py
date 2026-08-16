"""Global search: matching, role scoping, and its boundary with semantic search."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from app.core.config import settings
from app.models.enums import TaskStatus
from app.models.task import EmployeeTask
from tests.conftest import API
from tests.factories import make_png, upload_file

ANANYA = {
    "first_name": "Ananya",
    "last_name": "Sharma",
    "work_email": "ananya.search@example.com",
    "department": "Engineering",
    "designation": "Backend Engineer",
}
ROHIT = {
    "first_name": "Rohit",
    "last_name": "Verma",
    "work_email": "rohit.search@example.com",
    "department": "Finance",
    "designation": "Analyst",
}


def create_employee(client, hr_headers, payload) -> uuid.UUID:
    response = client.post(f"{API}/employees", json=payload, headers=hr_headers)
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["id"])


def register(client, email, password="Search@12345") -> dict[str, str]:
    files = sorted(Path(settings.EMAIL_OUTBOX_DIR).glob("*.txt"))
    token = re.search(r"accept-invite\?token=([A-Za-z0-9_\-]+)", files[-1].read_text()).group(1)
    client.post(f"{API}/onboarding/accept", json={"token": token, "password": password})
    tokens = client.post(
        f"{API}/auth/login", json={"email": email, "password": password}
    ).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def search(client, headers, q, **params) -> dict:
    response = client.get(f"{API}/search", headers=headers, params={"q": q, **params})
    assert response.status_code == 200, response.text
    return response.json()


def group(body: dict, kind: str) -> dict:
    return next(g for g in body["groups"] if g["kind"] == kind)


def titles(body: dict, kind: str) -> list[str]:
    return [item["title"] for item in group(body, kind)["items"]]


# --- Matching --------------------------------------------------------------


def test_finds_an_employee_by_name_code_email_and_department(client, hr_headers):
    employee_id = create_employee(client, hr_headers, ANANYA)
    code = client.get(f"{API}/employees/{employee_id}", headers=hr_headers).json()[
        "employee_code"
    ]

    for term in ("anan", "sharma", "ananya.search", code[:4], "engineer"):
        assert "Ananya Sharma" in titles(search(client, hr_headers, term), "employee"), term


def test_matches_a_full_name_spanning_both_columns(client, hr_headers):
    """"Ananya Sharma" lives in two columns; searching the whole name must work."""
    create_employee(client, hr_headers, ANANYA)
    assert "Ananya Sharma" in titles(search(client, hr_headers, "ananya sha"), "employee")


def test_search_is_case_insensitive(client, hr_headers):
    create_employee(client, hr_headers, ANANYA)
    assert titles(search(client, hr_headers, "ANANYA"), "employee") == ["Ananya Sharma"]


def test_hit_carries_a_link_and_status_badge(client, hr_headers):
    employee_id = create_employee(client, hr_headers, ANANYA)
    hit = group(search(client, hr_headers, "ananya"), "employee")["items"][0]

    assert hit["link"] == f"/employees/{employee_id}"
    assert hit["badge"] == "invited"
    assert hit["subtitle"].endswith("Engineering")


def test_finds_documents_and_tasks(client, hr_headers, db):
    employee_id = create_employee(client, hr_headers, ANANYA)
    upload_file(client, hr_headers, employee_id, data=make_png(),
                filename="passport-photo.png", document_type="photo")
    db.add(EmployeeTask(employee_id=employee_id, title="Complete security training",
                        category="training", status=TaskStatus.PENDING))
    db.commit()

    assert titles(search(client, hr_headers, "passport"), "document") == ["passport-photo.png"]
    assert titles(search(client, hr_headers, "security"), "task") == [
        "Complete security training"
    ]


def test_finds_knowledge_documents_by_title_and_body(client, hr_headers):
    client.post(
        f"{API}/knowledge/documents",
        json={
            "title": "Leave Policy",
            "category": "leave",
            "content": "Employees accrue eighteen days of annual leave each year.",
            "is_published": True,
        },
        headers=hr_headers,
    )

    assert titles(search(client, hr_headers, "leave pol"), "knowledge") == ["Leave Policy"]
    # Body text counts too — you rarely remember the exact document title.
    assert titles(search(client, hr_headers, "eighteen days"), "knowledge") == ["Leave Policy"]


def test_no_match_returns_empty_groups_not_an_error(client, hr_headers):
    create_employee(client, hr_headers, ANANYA)
    body = search(client, hr_headers, "zzzznothing")

    assert body["total"] == 0
    assert all(g["items"] == [] for g in body["groups"])


def test_a_wildcard_is_matched_literally(client, hr_headers):
    """A bare % must not behave as "match everything"."""
    create_employee(client, hr_headers, ANANYA)
    assert search(client, hr_headers, "%%")["total"] == 0


def test_a_single_character_query_is_rejected(client, hr_headers):
    assert client.get(f"{API}/search", headers=hr_headers, params={"q": "a"}).status_code == 422


def test_search_requires_authentication(client):
    assert client.get(f"{API}/search", params={"q": "ananya"}).status_code == 401


# --- Role scoping ----------------------------------------------------------


def test_employees_cannot_search_the_staff_directory(client, hr_headers):
    create_employee(client, hr_headers, ANANYA)
    headers = register(client, ANANYA["work_email"])
    create_employee(client, hr_headers, ROHIT)

    body = search(client, headers, "rohit")
    # The employee group is not merely empty — it is not offered at all.
    assert [g["kind"] for g in body["groups"]] == ["document", "task", "knowledge"]
    assert body["total"] == 0


def test_an_employee_sees_only_their_own_documents_and_tasks(client, hr_headers, db):
    ananya_id = create_employee(client, hr_headers, ANANYA)
    ananya_headers = register(client, ANANYA["work_email"])
    rohit_id = create_employee(client, hr_headers, ROHIT)

    upload_file(client, hr_headers, ananya_id, data=make_png(),
                filename="shared-name.png", document_type="photo")
    upload_file(client, hr_headers, rohit_id, data=make_png(),
                filename="shared-name.png", document_type="photo")
    db.add_all([
        EmployeeTask(employee_id=ananya_id, title="Shared task title", category="task"),
        EmployeeTask(employee_id=rohit_id, title="Shared task title", category="task"),
    ])
    db.commit()

    hr_view = search(client, hr_headers, "shared")
    assert group(hr_view, "document")["total"] == 2
    assert group(hr_view, "task")["total"] == 2

    employee_view = search(client, ananya_headers, "shared")
    assert group(employee_view, "document")["total"] == 1
    assert group(employee_view, "task")["total"] == 1
    assert group(employee_view, "document")["items"][0]["link"] == "/my-onboarding"


def test_employees_do_not_see_unpublished_knowledge(client, hr_headers):
    create_employee(client, hr_headers, ANANYA)
    headers = register(client, ANANYA["work_email"])
    created = client.post(
        f"{API}/knowledge/documents",
        json={
            "title": "Draft Bonus Policy",
            "category": "payroll",
            "content": "This bonus policy is still being finalised by the "
            "leadership team and has not been approved for publication yet.",
            "is_published": False,
        },
        headers=hr_headers,
    )
    assert created.status_code == 201, created.text

    assert titles(search(client, hr_headers, "bonus"), "knowledge") == ["Draft Bonus Policy"]
    assert titles(search(client, headers, "bonus"), "knowledge") == []


def test_a_user_with_no_employee_record_searches_nothing_personal(client, admin_headers, hr_headers):
    """Admin has no employee record, but is HR-scoped, so this checks the
    other side: staff-wide visibility rather than an empty personal scope."""
    employee_id = create_employee(client, hr_headers, ANANYA)
    upload_file(client, hr_headers, employee_id, data=make_png(),
                filename="admin-visible.png", document_type="photo")

    assert titles(search(client, admin_headers, "admin-visible"), "document") == [
        "admin-visible.png"
    ]


# --- Caps ------------------------------------------------------------------


def test_group_total_exceeds_the_capped_item_list(client, hr_headers):
    for index in range(6):
        create_employee(
            client,
            hr_headers,
            {**ANANYA, "work_email": f"ananya{index}@example.com",
             "last_name": f"Sharma{index}"},
        )

    employees = group(search(client, hr_headers, "ananya", limit=2), "employee")
    assert len(employees["items"]) == 2
    assert employees["total"] == 6
