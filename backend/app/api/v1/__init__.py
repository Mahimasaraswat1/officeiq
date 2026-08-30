"""Aggregates every v1 router under a single prefix (PRD B.6: /api/v1)."""

from fastapi import APIRouter

from app.api.v1 import (
    audit,
    auth,
    chat,
    dashboard,
    documents,
    employees,
    holidays,
    knowledge,
    notifications,
    onboarding,
    reports,
    search,
    tasks,
    users,
    verification,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(onboarding.router)
api_router.include_router(employees.router)
api_router.include_router(documents.router)
api_router.include_router(verification.router)
api_router.include_router(tasks.router)
api_router.include_router(knowledge.router)
api_router.include_router(chat.router)
api_router.include_router(dashboard.router)
api_router.include_router(search.router)
api_router.include_router(notifications.router)
api_router.include_router(reports.router)
api_router.include_router(users.router)
api_router.include_router(audit.router)
api_router.include_router(holidays.router)

__all__ = ["api_router"]
