"""Integration tests for the auth flow against a real Postgres."""

import pytest

from app.models.enums import UserRole
from app.services.auth_service import AuthService

EMAIL = "teacher@example.com"
PASSWORD = "correct-horse-9"


@pytest.fixture
async def teacher(db_session):
    return await AuthService(db_session).create_user(
        email=EMAIL, password=PASSWORD, full_name="Test Teacher", role=UserRole.TEACHER
    )


async def _login(client):
    resp = await client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_login_returns_token_pair(client, teacher):
    body = await _login(client)
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]


async def test_login_wrong_password_is_401_with_envelope(client, teacher):
    resp = await client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": "wrong-password"}
    )
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Incorrect email or password", "code": "authentication_failed"}


async def test_login_unknown_email_same_error_as_wrong_password(client, teacher):
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever-123"}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Incorrect email or password"


async def test_me_requires_and_accepts_bearer_token(client, teacher):
    assert (await client.get("/api/v1/auth/me")).status_code == 401

    body = await _login(client)
    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert resp.status_code == 200
    me = resp.json()
    assert me["email"] == EMAIL
    assert me["role"] == "teacher"


async def test_me_rejects_garbage_token(client, teacher):
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert resp.status_code == 401


async def test_refresh_rotates_tokens(client, teacher):
    first = await _login(client)
    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert resp.status_code == 200
    second = resp.json()
    assert second["refresh_token"] != first["refresh_token"]

    # New refresh token works.
    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}
    )
    assert resp.status_code == 200


async def test_refresh_reuse_revokes_family(client, teacher):
    first = await _login(client)
    ok = await client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert ok.status_code == 200
    second = ok.json()

    # Replaying the rotated (already-used) token must fail…
    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert resp.status_code == 401

    # …and, as reuse detection, kill the whole family including the new token.
    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}
    )
    assert resp.status_code == 401


async def test_logout_revokes_refresh_token(client, teacher):
    body = await _login(client)
    resp = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": body["refresh_token"]},
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert resp.status_code == 204

    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]}
    )
    assert resp.status_code == 401


async def test_inactive_user_cannot_login(client, db_session):
    await AuthService(db_session).create_user(
        email="off@example.com",
        password="password-123",
        full_name="Disabled",
        role=UserRole.TEACHER,
        is_active=False,
    )
    resp = await client.post(
        "/api/v1/auth/login", json={"email": "off@example.com", "password": "password-123"}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Account is disabled"
