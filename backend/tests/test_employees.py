"""Employee CRUD, RBAC boundaries, and search/filter behaviour."""

from __future__ import annotations

from tests.conftest import API

NEW_EMPLOYEE = {
    "first_name": "Ananya",
    "last_name": "Sharma",
    "work_email": "ananya.sharma@example.com",
    "department": "Engineering",
    "designation": "Software Engineer",
}


def create_employee(client, headers, **overrides) -> dict:
    payload = {**NEW_EMPLOYEE, **overrides}
    response = client.post(f"{API}/employees", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_hr_can_create_an_employee_with_a_generated_code(client, hr_headers):
    employee = create_employee(client, hr_headers)
    assert employee["employee_code"] == "EMP0001"
    assert employee["onboarding_status"] == "invited"
    assert employee["user_id"] is None


def test_work_email_is_normalised_to_lowercase(client, hr_headers):
    employee = create_employee(client, hr_headers, work_email="MiXeD.Case@Example.Com")
    assert employee["work_email"] == "mixed.case@example.com"


def test_duplicate_work_email_is_a_conflict(client, hr_headers):
    create_employee(client, hr_headers)
    response = client.post(f"{API}/employees", json=NEW_EMPLOYEE, headers=hr_headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_creating_an_employee_writes_an_invitation_email_to_the_outbox(client, hr_headers):
    from pathlib import Path
    from app.core.config import settings

    outbox = Path(settings.EMAIL_OUTBOX_DIR)
    before = len(list(outbox.glob("*.txt"))) if outbox.exists() else 0

    create_employee(client, hr_headers)

    files = sorted(outbox.glob("*.txt"))
    assert len(files) == before + 1
    content = files[-1].read_text()
    assert "accept-invite?token=" in content
    assert NEW_EMPLOYEE["work_email"] in content


def test_send_invite_false_skips_the_email(client, hr_headers):
    response = client.post(
        f"{API}/employees",
        json={**NEW_EMPLOYEE, "send_invite": False},
        headers=hr_headers,
    )
    assert response.status_code == 201
    invitations = client.get(
        f"{API}/employees/{response.json()['id']}/invitations", headers=hr_headers
    )
    assert invitations.json() == []


def test_employee_role_cannot_list_employees(client, hr_headers, db):
    """An employee account is blocked by the HR guard on the list endpoint."""
    from app.core.security import hash_password
    from app.models.enums import UserRole
    from app.models.user import User
    from tests.conftest import auth_headers

    db.add(
        User(
            email="staffer@example.com",
            hashed_password=hash_password("Staffer@123"),
            full_name="Staffer",
            role=UserRole.EMPLOYEE,
        )
    )
    db.commit()

    headers = auth_headers(client, "staffer@example.com", "Staffer@123")
    response = client.get(f"{API}/employees", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_listing_requires_authentication(client):
    assert client.get(f"{API}/employees").status_code == 401


def test_search_and_status_filters(client, hr_headers):
    create_employee(client, hr_headers)
    create_employee(
        client,
        hr_headers,
        first_name="Rohit",
        last_name="Verma",
        work_email="rohit.verma@example.com",
        department="Finance",
    )

    by_name = client.get(f"{API}/employees?search=rohit", headers=hr_headers).json()
    assert by_name["total"] == 1
    assert by_name["items"][0]["first_name"] == "Rohit"

    by_dept = client.get(
        f"{API}/employees?department=engineering", headers=hr_headers
    ).json()
    assert by_dept["total"] == 1

    by_status = client.get(
        f"{API}/employees?onboarding_status=complete", headers=hr_headers
    ).json()
    assert by_status["total"] == 0


def test_pagination_metadata(client, hr_headers):
    for index in range(3):
        create_employee(client, hr_headers, work_email=f"person{index}@example.com")

    page = client.get(f"{API}/employees?page=1&page_size=2", headers=hr_headers).json()
    assert page["total"] == 3
    assert page["pages"] == 2
    assert len(page["items"]) == 2


def test_update_sets_completion_timestamp(client, hr_headers):
    employee = create_employee(client, hr_headers)
    response = client.patch(
        f"{API}/employees/{employee['id']}",
        json={"onboarding_status": "complete"},
        headers=hr_headers,
    )
    assert response.status_code == 200
    assert response.json()["onboarding_completed_at"] is not None


def test_partial_update_leaves_other_fields_untouched(client, hr_headers):
    employee = create_employee(client, hr_headers)
    response = client.patch(
        f"{API}/employees/{employee['id']}",
        json={"designation": "Senior Software Engineer"},
        headers=hr_headers,
    )
    assert response.status_code == 200
    assert response.json()["designation"] == "Senior Software Engineer"
    assert response.json()["department"] == "Engineering"


def test_hr_cannot_delete_only_admin_can(client, hr_headers, admin_headers):
    employee = create_employee(client, hr_headers)

    denied = client.delete(f"{API}/employees/{employee['id']}", headers=hr_headers)
    assert denied.status_code == 403

    allowed = client.delete(f"{API}/employees/{employee['id']}", headers=admin_headers)
    assert allowed.status_code == 200
    assert client.get(f"{API}/employees/{employee['id']}", headers=admin_headers).status_code == 404


def test_unknown_employee_returns_404_envelope(client, hr_headers):
    response = client.get(
        f"{API}/employees/00000000-0000-0000-0000-000000000000", headers=hr_headers
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
