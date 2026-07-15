"""Smoke tests for the application scaffold (no database required)."""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def app():
    from app.main import create_app

    return create_app()


async def test_app_boots_and_registers_health_route(app):
    paths = {route.path for route in app.routes}
    assert "/health" in paths


async def test_unknown_route_returns_404(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/nope")
    assert resp.status_code == 404


def test_all_models_are_registered():
    from app.db.base import Base

    tables = set(Base.metadata.tables)
    assert tables == {
        "users",
        "refresh_tokens",
        "classes",
        "students",
        "enrollments",
        "student_face_images",
        "face_embeddings",
        "attendance_sessions",
        "session_images",
        "face_detections",
        "attendance_records",
        "audit_logs",
    }
