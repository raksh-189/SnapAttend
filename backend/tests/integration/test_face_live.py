"""Opt-in tests against the REAL InsightFace engine.

Skipped unless FACE_LIVE_TESTS=1 — first run downloads/loads the buffalo_l
ONNX models (seconds, ~300 MB), too heavy for the default suite. Run:

    FACE_LIVE_TESTS=1 pytest tests/integration/test_face_live.py -q
"""

import os

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("FACE_LIVE_TESTS") != "1",
    reason="live InsightFace tests are opt-in (FACE_LIVE_TESTS=1)",
)


@pytest.fixture(scope="module")
def engine():
    from app.services.face.engine import get_face_engine

    return get_face_engine()


def _blank_jpeg(w: int = 320, h: int = 240) -> bytes:
    img = np.full((h, w, 3), 128, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def test_engine_loads_and_reports_model(engine):
    assert engine.model_name  # buffalo_l by default


def test_blank_image_has_no_faces(engine):
    assert engine.detect(_blank_jpeg()) == []


def test_undecodable_bytes_raise(engine):
    with pytest.raises(ValueError):
        engine.detect(b"\xff\xd8\xffnot really a jpeg")


def test_detect_returns_normalized_embeddings(engine):
    """Any face the detector finds must come back with a unit-norm 512-d
    embedding. Uses a real photo if one is provided via FACE_LIVE_PHOTO."""
    photo = os.environ.get("FACE_LIVE_PHOTO")
    if not photo:
        pytest.skip("set FACE_LIVE_PHOTO=/path/to/face.jpg to run")
    with open(photo, "rb") as fh:
        faces = engine.detect(fh.read())
    assert len(faces) >= 1
    for face in faces:
        assert face.embedding.shape == (512,)
        assert face.embedding.dtype == np.float32
        assert np.linalg.norm(face.embedding) == pytest.approx(1.0, abs=1e-3)
        x, y, w, h = face.bbox
        assert w > 0 and h > 0
