"""Integration tests for classes, students, and enrollments."""

import pytest

from app.models.enums import UserRole
from app.services.auth_service import AuthService


@pytest.fixture
async def users(db_session):
    """Two teachers + one admin, with login helpers."""
    svc = AuthService(db_session)
    teacher1 = await svc.create_user(
        email="t1@example.com", password="password-t1", full_name="Teacher One",
        role=UserRole.TEACHER,
    )
    teacher2 = await svc.create_user(
        email="t2@example.com", password="password-t2", full_name="Teacher Two",
        role=UserRole.TEACHER,
    )
    admin = await svc.create_user(
        email="a@example.com", password="password-ad", full_name="Admin",
        role=UserRole.ADMIN,
    )
    return {"teacher1": teacher1, "teacher2": teacher2, "admin": admin}


async def _auth(client, email, password):
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
async def t1_headers(client, users):
    return await _auth(client, "t1@example.com", "password-t1")


@pytest.fixture
async def t2_headers(client, users):
    return await _auth(client, "t2@example.com", "password-t2")


@pytest.fixture
async def admin_headers(client, users):
    return await _auth(client, "a@example.com", "password-ad")


async def _create_class(client, headers, code="CS101"):
    resp = await client.post(
        "/api/v1/classes", json={"code": code, "name": "Intro", "room_type": "laboratory"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_student(client, headers, reg="R001", name="Alice Zed"):
    resp = await client.post(
        "/api/v1/students", json={"reg_number": reg, "full_name": name}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- Students --------------------------------------------------------------


async def test_student_crud_roundtrip(client, t1_headers):
    student = await _create_student(client, t1_headers)
    sid = student["id"]
    assert student["reg_number"] == "R001"

    resp = await client.patch(
        f"/api/v1/students/{sid}", json={"email": "Alice@Example.com"}, headers=t1_headers
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "alice@example.com"  # normalized

    resp = await client.delete(f"/api/v1/students/{sid}", headers=t1_headers)
    assert resp.status_code == 204
    resp = await client.get(f"/api/v1/students/{sid}", headers=t1_headers)
    assert resp.json()["is_active"] is False  # soft delete


async def test_duplicate_reg_number_conflicts(client, t1_headers):
    await _create_student(client, t1_headers)
    resp = await client.post(
        "/api/v1/students", json={"reg_number": "R001", "full_name": "Dup"}, headers=t1_headers
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "conflict"


async def test_student_search_and_paging(client, t1_headers):
    for i in range(3):
        await _create_student(client, t1_headers, reg=f"R00{i}", name=f"Student {i}")
    resp = await client.get("/api/v1/students?q=R00&limit=2", headers=t1_headers)
    body = resp.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2

    resp = await client.get("/api/v1/students?q=Student 2", headers=t1_headers)
    assert [s["reg_number"] for s in resp.json()["items"]] == ["R002"]


async def test_students_require_auth(client):
    assert (await client.get("/api/v1/students")).status_code == 401


# --- Classes ---------------------------------------------------------------


async def test_class_crud_and_teacher_ownership(client, users, t1_headers):
    cls = await _create_class(client, t1_headers)
    assert cls["teacher_id"] == str(users["teacher1"].id)
    assert cls["room_type"] == "laboratory"

    resp = await client.patch(
        f"/api/v1/classes/{cls['id']}", json={"name": "Renamed"}, headers=t1_headers
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"


async def test_duplicate_class_code_conflicts(client, t1_headers):
    await _create_class(client, t1_headers)
    resp = await client.post(
        "/api/v1/classes", json={"code": "CS101", "name": "Other"}, headers=t1_headers
    )
    assert resp.status_code == 409


async def test_other_teacher_cannot_touch_class(client, t1_headers, t2_headers):
    cls = await _create_class(client, t1_headers)
    resp = await client.get(f"/api/v1/classes/{cls['id']}", headers=t2_headers)
    assert resp.status_code == 403
    resp = await client.patch(
        f"/api/v1/classes/{cls['id']}", json={"name": "Hijack"}, headers=t2_headers
    )
    assert resp.status_code == 403


async def test_admin_sees_all_teachers_see_own(client, t1_headers, t2_headers, admin_headers):
    await _create_class(client, t1_headers, code="CS101")
    await _create_class(client, t2_headers, code="CS102")

    assert (await client.get("/api/v1/classes", headers=t1_headers)).json()["total"] == 1
    assert (await client.get("/api/v1/classes", headers=admin_headers)).json()["total"] == 2


async def test_admin_can_assign_teacher(client, users, admin_headers):
    resp = await client.post(
        "/api/v1/classes",
        json={"code": "CS200", "name": "Assigned", "teacher_id": str(users["teacher2"].id)},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["teacher_id"] == str(users["teacher2"].id)


# --- Enrollments -----------------------------------------------------------


async def test_enroll_roster_unenroll_flow(client, t1_headers):
    cls = await _create_class(client, t1_headers)
    s1 = await _create_student(client, t1_headers, reg="R001", name="Alice")
    s2 = await _create_student(client, t1_headers, reg="R002", name="Bob")

    resp = await client.post(
        f"/api/v1/classes/{cls['id']}/enrollments",
        json={"student_ids": [s1["id"], s2["id"]]},
        headers=t1_headers,
    )
    assert resp.status_code == 200, resp.text
    assert {e["student"]["reg_number"] for e in resp.json()} == {"R001", "R002"}

    # Idempotent re-enroll.
    resp = await client.post(
        f"/api/v1/classes/{cls['id']}/enrollments",
        json={"student_ids": [s1["id"]]},
        headers=t1_headers,
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 2

    resp = await client.delete(
        f"/api/v1/classes/{cls['id']}/enrollments/{s2['id']}", headers=t1_headers
    )
    assert resp.status_code == 204
    roster = (
        await client.get(f"/api/v1/classes/{cls['id']}/enrollments", headers=t1_headers)
    ).json()
    assert [e["student"]["reg_number"] for e in roster] == ["R001"]


async def test_enroll_unknown_student_404(client, t1_headers):
    cls = await _create_class(client, t1_headers)
    resp = await client.post(
        f"/api/v1/classes/{cls['id']}/enrollments",
        json={"student_ids": ["00000000-0000-0000-0000-000000000000"]},
        headers=t1_headers,
    )
    assert resp.status_code == 404


async def test_other_teacher_cannot_enroll(client, t1_headers, t2_headers):
    cls = await _create_class(client, t1_headers)
    s1 = await _create_student(client, t2_headers, reg="R009", name="Eve")
    resp = await client.post(
        f"/api/v1/classes/{cls['id']}/enrollments",
        json={"student_ids": [s1["id"]]},
        headers=t2_headers,
    )
    assert resp.status_code == 403


async def test_cannot_enroll_inactive_student(client, t1_headers):
    cls = await _create_class(client, t1_headers)
    s1 = await _create_student(client, t1_headers)
    await client.delete(f"/api/v1/students/{s1['id']}", headers=t1_headers)

    resp = await client.post(
        f"/api/v1/classes/{cls['id']}/enrollments",
        json={"student_ids": [s1["id"]]},
        headers=t1_headers,
    )
    assert resp.status_code == 409
