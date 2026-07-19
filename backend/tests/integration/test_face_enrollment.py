"""Integration tests for face enrollment with a fake engine.

The real InsightFace engine is process-heavy; these tests exercise the full
HTTP → service → DB → storage path with a deterministic stand-in. The real
engine is covered by tests/integration/test_face_live.py (opt-in).
"""

import uuid
from dataclasses import dataclass

import numpy as np
import pytest

from app.models.enums import UserRole
from app.services.auth_service import AuthService
from app.services.face.engine import get_face_engine
from app.storage.local import LocalStorage, get_storage

JPEG = b"\xff\xd8\xff\xe0" + b"fake-jpeg-body" * 10


@dataclass
class _FakeFace:
    bbox: tuple
    embedding: np.ndarray
    det_score: float


class FakeEngine:
    """Deterministic engine: returns `faces_to_return` faces per detect()."""

    model_name = "fake_model"

    def __init__(self):
        self.faces_to_return = 1

    def detect(self, image_bytes: bytes):
        rng = np.random.default_rng(seed=len(image_bytes))
        out = []
        for _ in range(self.faces_to_return):
            v = rng.standard_normal(512).astype(np.float32)
            out.append(
                _FakeFace(bbox=(10, 10, 50, 50), embedding=v / np.linalg.norm(v),
                          det_score=0.93)
            )
        return out


@pytest.fixture
def fake_engine():
    return FakeEngine()


@pytest.fixture
async def face_client(client, fake_engine, tmp_path):
    """The shared `client` app, with engine + storage overridden."""
    app = client._transport.app  # ASGITransport wraps the FastAPI app
    storage = LocalStorage(root=str(tmp_path))
    app.dependency_overrides[get_face_engine] = lambda: fake_engine
    app.dependency_overrides[get_storage] = lambda: storage
    client.storage = storage
    yield client


@pytest.fixture
async def headers(face_client, db_session):
    await AuthService(db_session).create_user(
        email="t@example.com", password="password-tt", full_name="T",
        role=UserRole.TEACHER,
    )
    resp = await face_client.post(
        "/api/v1/auth/login", json={"email": "t@example.com", "password": "password-tt"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
async def student_id(face_client, headers):
    resp = await face_client.post(
        "/api/v1/students", json={"reg_number": "R100", "full_name": "Face Kid"},
        headers=headers,
    )
    return resp.json()["id"]


async def _upload(client, headers, student_id, body=JPEG, name="a.jpg", mime="image/jpeg"):
    return await client.post(
        f"/api/v1/students/{student_id}/face-images",
        files={"file": (name, body, mime)},
        headers=headers,
    )


async def test_enroll_photo_creates_embedding_and_stores_file(
    face_client, headers, student_id
):
    resp = await _upload(face_client, headers, student_id)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["quality_score"] == pytest.approx(0.93)
    assert body["embeddings_total"] == 1
    assert body["image"]["student_id"] == student_id

    # File landed in storage under the enrollment/ prefix.
    rows = (
        await face_client.get(
            f"/api/v1/students/{student_id}/face-images", headers=headers
        )
    ).json()
    assert len(rows) == 1


async def test_multiple_photos_accumulate_embeddings(face_client, headers, student_id):
    for i in range(3):
        resp = await _upload(face_client, headers, student_id, body=JPEG + bytes([i]))
        assert resp.status_code == 201
    assert resp.json()["embeddings_total"] == 3


async def test_sixth_photo_rejected(face_client, headers, student_id):
    for i in range(5):
        assert (
            await _upload(face_client, headers, student_id, body=JPEG + bytes([i]))
        ).status_code == 201
    resp = await _upload(face_client, headers, student_id, body=JPEG + b"x6")
    assert resp.status_code == 409


async def test_no_face_rejected(face_client, fake_engine, headers, student_id):
    fake_engine.faces_to_return = 0
    resp = await _upload(face_client, headers, student_id)
    assert resp.status_code == 422
    assert "No face detected" in resp.json()["detail"]


async def test_multiple_faces_rejected(face_client, fake_engine, headers, student_id):
    fake_engine.faces_to_return = 2
    resp = await _upload(face_client, headers, student_id)
    assert resp.status_code == 422
    assert "exactly one" in resp.json()["detail"]


async def test_non_image_rejected(face_client, headers, student_id):
    resp = await _upload(
        face_client, headers, student_id, body=b"not an image", name="a.txt",
        mime="text/plain",
    )
    assert resp.status_code == 422


async def test_unknown_student_404(face_client, headers):
    resp = await _upload(face_client, headers, str(uuid.uuid4()))
    assert resp.status_code == 404


async def test_delete_face_image_removes_embeddings_and_file(
    face_client, headers, student_id
):
    resp = await _upload(face_client, headers, student_id)
    image_id = resp.json()["image"]["id"]

    resp = await face_client.delete(
        f"/api/v1/students/{student_id}/face-images/{image_id}", headers=headers
    )
    assert resp.status_code == 204

    rows = (
        await face_client.get(
            f"/api/v1/students/{student_id}/face-images", headers=headers
        )
    ).json()
    assert rows == []


async def test_right_to_erasure_purges_everything(face_client, headers, student_id):
    for i in range(2):
        await _upload(face_client, headers, student_id, body=JPEG + bytes([i]))

    resp = await face_client.delete(
        f"/api/v1/students/{student_id}/biometrics", headers=headers
    )
    assert resp.status_code == 204

    rows = (
        await face_client.get(
            f"/api/v1/students/{student_id}/face-images", headers=headers
        )
    ).json()
    assert rows == []
    # Student record itself survives (only biometrics are erased).
    resp = await face_client.get(f"/api/v1/students/{student_id}", headers=headers)
    assert resp.status_code == 200


async def test_duplicate_image_rejected(face_client, headers, student_id):
    assert (await _upload(face_client, headers, student_id)).status_code == 201
    resp = await _upload(face_client, headers, student_id)  # same bytes again
    assert resp.status_code == 409
    assert "already enrolled" in resp.json()["detail"]


async def test_batch_upload_mixed_outcomes(face_client, fake_engine, headers, student_id):
    """One good photo, one duplicate of it, one non-image: the good one is
    enrolled, the rest are skipped with per-file reasons."""
    good = JPEG + b"batch-1"
    resp = await face_client.post(
        f"/api/v1/students/{student_id}/face-images/batch",
        files=[
            ("files", ("one.jpg", good, "image/jpeg")),
            ("files", ("dup.jpg", good, "image/jpeg")),
            ("files", ("bad.txt", b"not an image", "text/plain")),
        ],
        headers=headers,
    )
    assert resp.status_code == 207, resp.text
    body = resp.json()
    assert body["enrolled"] == 1
    assert body["skipped"] == 2
    assert body["embeddings_total"] == 1
    by_name = {r["filename"]: r for r in body["results"]}
    assert by_name["one.jpg"]["enrolled"] is True
    assert by_name["dup.jpg"]["enrolled"] is False
    assert "already enrolled" in by_name["dup.jpg"]["error"]
    assert by_name["bad.txt"]["enrolled"] is False
    assert "JPEG or PNG" in by_name["bad.txt"]["error"]


async def test_batch_all_invalid_enrolls_nothing(face_client, fake_engine, headers, student_id):
    fake_engine.faces_to_return = 0  # no face in any photo
    resp = await face_client.post(
        f"/api/v1/students/{student_id}/face-images/batch",
        files=[
            ("files", ("a.jpg", JPEG + b"a", "image/jpeg")),
            ("files", ("b.jpg", JPEG + b"b", "image/jpeg")),
        ],
        headers=headers,
    )
    assert resp.status_code == 207
    body = resp.json()
    assert body["enrolled"] == 0 and body["skipped"] == 2
    assert body["embeddings_total"] == 0
    assert all("No face detected" in r["error"] for r in body["results"])


async def test_batch_unknown_student_404(face_client, headers):
    resp = await face_client.post(
        f"/api/v1/students/{uuid.uuid4()}/face-images/batch",
        files=[("files", ("a.jpg", JPEG, "image/jpeg"))],
        headers=headers,
    )
    assert resp.status_code == 404


async def test_face_endpoints_require_auth(face_client, student_id):
    resp = await face_client.post(f"/api/v1/students/{student_id}/face-images")
    assert resp.status_code == 401
