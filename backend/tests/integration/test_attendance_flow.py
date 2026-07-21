"""End-to-end attendance flow with a deterministic fake engine.

Covers: session upload (202) → background pipeline (detect, match against
the class gallery, dedupe, drafts) → review board payload → overrides,
unknown-face resolution, confirm, and the state-machine guards.

httpx's ASGITransport awaits BackgroundTasks before returning the response,
so the pipeline has always run by the time a POST /sessions call returns.
"""

import uuid
from dataclasses import dataclass

import numpy as np
import pytest

from app.db.session import get_session_factory
from app.models.enums import UserRole
from app.services.auth_service import AuthService
from app.services.face.engine import get_face_engine
from app.storage.local import LocalStorage, get_storage

JPEG = b"\xff\xd8\xff\xe0" + b"fake-jpeg-body" * 10


def _unit(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed=seed)
    v = rng.standard_normal(512).astype(np.float32)
    return v / np.linalg.norm(v)


@dataclass
class _FakeFace:
    bbox: tuple
    embedding: np.ndarray
    det_score: float


class FakeEngine:
    """Deterministic engine.

    detect() returns faces scripted per-image via `script`: a dict mapping
    the image bytes' last byte → list of (seed, det_score). Enrollment
    photos reuse seeds so classroom faces cosine-match enrolled students.
    """

    model_name = "fake_model"

    def __init__(self):
        self.script: dict[int, list[tuple[int, float]]] = {}

    def detect(self, image_bytes: bytes):
        plan = self.script.get(image_bytes[-1], [(image_bytes[-1], 0.9)])
        return [
            _FakeFace(bbox=(10, 10, 50, 50), embedding=_unit(seed), det_score=score)
            for seed, score in plan
        ]

    def crop(self, image_bytes: bytes, bbox):
        return b"\xff\xd8\xff\xe0crop"


@pytest.fixture
def fake_engine():
    return FakeEngine()


@pytest.fixture
async def att_client(client, fake_engine, tmp_path, test_engine):
    """Shared app with engine, storage, and pipeline session factory overridden."""
    from sqlalchemy.ext.asyncio import async_sessionmaker as factory_cls

    app = client._transport.app
    storage = LocalStorage(root=str(tmp_path))
    test_factory = factory_cls(test_engine, expire_on_commit=False, autoflush=False)
    app.dependency_overrides[get_face_engine] = lambda: fake_engine
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_session_factory] = lambda: test_factory
    client.storage = storage
    yield client


@pytest.fixture
async def headers(att_client, db_session):
    await AuthService(db_session).create_user(
        email="t@example.com", password="password-tt", full_name="T",
        role=UserRole.TEACHER,
    )
    resp = await att_client.post(
        "/api/v1/auth/login", json={"email": "t@example.com", "password": "password-tt"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
async def classroom(att_client, headers, fake_engine):
    """A class with 3 enrolled students, each with one enrolled face
    (seeds 1, 2, 3)."""
    resp = await att_client.post(
        "/api/v1/classes", json={"code": "CS101", "name": "Intro"}, headers=headers
    )
    class_id = resp.json()["id"]

    student_ids = {}
    for i, seed in enumerate((1, 2, 3), start=1):
        resp = await att_client.post(
            "/api/v1/students",
            json={"reg_number": f"R{i}", "full_name": f"Student {i}"},
            headers=headers,
        )
        sid = resp.json()["id"]
        student_ids[seed] = sid
        # Enrollment photo whose last byte scripts one face with this seed.
        photo = JPEG + bytes([seed])
        fake_engine.script[seed] = [(seed, 0.95)]
        resp = await att_client.post(
            f"/api/v1/students/{sid}/face-images",
            files={"file": (f"s{seed}.jpg", photo, "image/jpeg")},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text

    resp = await att_client.post(
        f"/api/v1/classes/{class_id}/enrollments",
        json={"student_ids": list(student_ids.values())},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return {"class_id": class_id, "students": student_ids}


async def _create_session(att_client, headers, class_id, photos):
    return await att_client.post(
        "/api/v1/attendance/sessions",
        data={"class_id": class_id, "session_date": "2026-07-21"},
        files=[("files", (f"img{i}.jpg", p, "image/jpeg")) for i, p in enumerate(photos)],
        headers=headers,
    )


async def test_full_flow_two_images_dedupe_and_unknown(
    att_client, fake_engine, headers, classroom
):
    """Student 1 in both photos (dedupe → one present record), student 2 in
    one, student 3 absent, plus one unknown face."""
    # Photo A (last byte 100): student1 strong, student2, and a stranger.
    fake_engine.script[100] = [(1, 0.9), (2, 0.9), (999, 0.9)]
    # Photo B (last byte 101): student1 again (weaker sighting).
    fake_engine.script[101] = [(1, 0.85)]

    resp = await _create_session(
        att_client, headers, classroom["class_id"], [JPEG + bytes([100]), JPEG + bytes([101])]
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["images_accepted"] == 2
    session_id = body["session_id"]

    resp = await att_client.get(f"/api/v1/attendance/sessions/{session_id}", headers=headers)
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["session"]["status"] == "pending_review"

    # Evidence: 4 detections across 2 images.
    detections = [d for img in detail["images"] for d in img["detections"]]
    assert len(detections) == 4
    by_status: dict[str, int] = {}
    for d in detections:
        by_status[d["match_status"]] = by_status.get(d["match_status"], 0) + 1
    # Student 1 seen twice → 1 matched + 1 duplicate; student 2 matched; stranger unknown.
    assert by_status == {"matched": 2, "duplicate": 1, "unknown": 1}

    # Verdicts: one record per roster student.
    records = {r["student"]["reg_number"]: r for r in detail["records"]}
    assert set(records) == {"R1", "R2", "R3"}
    assert records["R1"]["status"] == "present" and records["R1"]["source"] == "ai"
    assert records["R2"]["status"] == "present"
    assert records["R3"]["status"] == "absent"

    # Crop thumbnails are served with ownership enforced.
    resp = await att_client.get(
        f"/api/v1/attendance/sessions/{session_id}/detections/{detections[0]['id']}/crop",
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"


async def test_review_override_resolve_confirm(att_client, fake_engine, headers, classroom):
    fake_engine.script[100] = [(1, 0.9), (999, 0.9)]  # student1 + a stranger
    resp = await _create_session(att_client, headers, classroom["class_id"], [JPEG + bytes([100])])
    session_id = resp.json()["session_id"]

    detail = (
        await att_client.get(f"/api/v1/attendance/sessions/{session_id}", headers=headers)
    ).json()
    records = {r["student"]["reg_number"]: r for r in detail["records"]}
    unknown = next(
        d
        for img in detail["images"]
        for d in img["detections"]
        if d["match_status"] == "unknown"
    )

    # Teacher marks absent student 3 late (manual override).
    s3 = records["R3"]["student"]["id"]
    resp = await att_client.patch(
        f"/api/v1/attendance/sessions/{session_id}/records/{s3}",
        json={"status": "late"},
        headers=headers,
    )
    assert resp.status_code == 204

    # The unknown face turns out to be student 2 → assign + mark present.
    s2 = records["R2"]["student"]["id"]
    resp = await att_client.post(
        f"/api/v1/attendance/sessions/{session_id}/detections/{unknown['id']}/resolve",
        json={"student_id": s2},
        headers=headers,
    )
    assert resp.status_code == 204

    # Confirm.
    resp = await att_client.post(
        f"/api/v1/attendance/sessions/{session_id}/confirm", headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed"
    assert resp.json()["confirmed_at"] is not None

    detail = (
        await att_client.get(f"/api/v1/attendance/sessions/{session_id}", headers=headers)
    ).json()
    records = {r["student"]["reg_number"]: r for r in detail["records"]}
    assert records["R1"]["status"] == "present" and records["R1"]["source"] == "ai"
    assert records["R2"]["status"] == "present" and records["R2"]["source"] == "manual"
    assert records["R3"]["status"] == "late" and records["R3"]["source"] == "manual"


async def test_confirmed_session_rejects_edits(att_client, fake_engine, headers, classroom):
    fake_engine.script[100] = [(1, 0.9)]
    resp = await _create_session(att_client, headers, classroom["class_id"], [JPEG + bytes([100])])
    session_id = resp.json()["session_id"]
    await att_client.post(f"/api/v1/attendance/sessions/{session_id}/confirm", headers=headers)

    s1 = classroom["students"][1]
    resp = await att_client.patch(
        f"/api/v1/attendance/sessions/{session_id}/records/{s1}",
        json={"status": "absent"},
        headers=headers,
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "invalid_state"

    # Double-confirm is also an illegal transition.
    resp = await att_client.post(
        f"/api/v1/attendance/sessions/{session_id}/confirm", headers=headers
    )
    assert resp.status_code == 409


async def test_resolve_matched_detection_rejected(att_client, fake_engine, headers, classroom):
    fake_engine.script[100] = [(1, 0.9)]
    resp = await _create_session(att_client, headers, classroom["class_id"], [JPEG + bytes([100])])
    session_id = resp.json()["session_id"]

    detail = (
        await att_client.get(f"/api/v1/attendance/sessions/{session_id}", headers=headers)
    ).json()
    matched = detail["images"][0]["detections"][0]
    assert matched["match_status"] == "matched"

    resp = await att_client.post(
        f"/api/v1/attendance/sessions/{session_id}/detections/{matched['id']}/resolve",
        json={"student_id": classroom["students"][2]},
        headers=headers,
    )
    assert resp.status_code == 409


async def test_low_quality_face_not_matched(att_client, fake_engine, headers, classroom):
    """A face below the session det-score floor stays evidence-only."""
    fake_engine.script[100] = [(1, 0.2)]  # student 1, but blurry
    resp = await _create_session(att_client, headers, classroom["class_id"], [JPEG + bytes([100])])
    session_id = resp.json()["session_id"]

    detail = (
        await att_client.get(f"/api/v1/attendance/sessions/{session_id}", headers=headers)
    ).json()
    detections = [d for img in detail["images"] for d in img["detections"]]
    assert [d["match_status"] for d in detections] == ["low_quality"]
    records = {r["student"]["reg_number"]: r for r in detail["records"]}
    assert all(r["status"] == "absent" for r in records.values())


async def test_other_teacher_cannot_touch_session(att_client, fake_engine, headers, classroom, db_session):
    fake_engine.script[100] = [(1, 0.9)]
    resp = await _create_session(att_client, headers, classroom["class_id"], [JPEG + bytes([100])])
    session_id = resp.json()["session_id"]

    await AuthService(db_session).create_user(
        email="other@example.com", password="password-oo", full_name="O",
        role=UserRole.TEACHER,
    )
    resp = await att_client.post(
        "/api/v1/auth/login", json={"email": "other@example.com", "password": "password-oo"}
    )
    other = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    assert (
        await att_client.get(f"/api/v1/attendance/sessions/{session_id}", headers=other)
    ).status_code == 403
    assert (
        await att_client.post(
            f"/api/v1/attendance/sessions/{session_id}/confirm", headers=other
        )
    ).status_code == 403


async def test_session_rejects_non_image_batch_atomically(att_client, headers, classroom):
    resp = await att_client.post(
        "/api/v1/attendance/sessions",
        data={"class_id": classroom["class_id"], "session_date": "2026-07-21"},
        files=[
            ("files", ("ok.jpg", JPEG + bytes([100]), "image/jpeg")),
            ("files", ("bad.txt", b"not an image", "text/plain")),
        ],
        headers=headers,
    )
    assert resp.status_code == 422  # whole batch rejected, no session created

    resp = await att_client.get(
        f"/api/v1/attendance/classes/{classroom['class_id']}/sessions", headers=headers
    )
    assert resp.json()["total"] == 0


async def test_list_class_sessions(att_client, fake_engine, headers, classroom):
    fake_engine.script[100] = [(1, 0.9)]
    for _ in range(2):
        await _create_session(att_client, headers, classroom["class_id"], [JPEG + bytes([100])])
    resp = await att_client.get(
        f"/api/v1/attendance/classes/{classroom['class_id']}/sessions", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert all(s["status"] == "pending_review" for s in body["items"])


async def test_attendance_requires_auth(att_client):
    resp = await att_client.get(f"/api/v1/attendance/sessions/{uuid.uuid4()}")
    assert resp.status_code == 401
