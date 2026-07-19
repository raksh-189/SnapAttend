"""InsightFace engine singleton — the ONLY module importing insightface.

Loaded once (lifespan or first use); inference is synchronous CPU work,
so callers run it off the event loop (asyncio.to_thread / BackgroundTasks).
"""

from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class DetectedFace:
    bbox: tuple[int, int, int, int]  # x, y, w, h (clamped to image bounds)
    embedding: np.ndarray  # L2-normalized, float32, shape (512,)
    det_score: float  # detector confidence 0..1


class FaceEngine:
    def __init__(self) -> None:
        # Deferred import: keeps app importable (and unit tests runnable)
        # where insightface isn't installed.
        from insightface.app import FaceAnalysis

        settings = get_settings()
        self._app = FaceAnalysis(
            name=settings.FACE_MODEL_NAME,
            root=settings.FACE_MODEL_ROOT,
            providers=["CPUExecutionProvider"],
            allowed_modules=["detection", "recognition"],
        )
        det = settings.FACE_DET_SIZE
        self._app.prepare(ctx_id=-1, det_size=(det, det))
        self.model_name = settings.FACE_MODEL_NAME
        logger.info("face_engine_loaded", model=self.model_name, det_size=det)

    def detect(self, image_bytes: bytes) -> list[DetectedFace]:
        """Detect + embed every face in an image. Raises ValueError on
        undecodable input."""
        buf = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Could not decode image")

        h, w = img.shape[:2]
        faces = []
        for face in self._app.get(img):
            x1, y1, x2, y2 = face.bbox.astype(int)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            embedding = face.embedding.astype(np.float32)
            norm = np.linalg.norm(embedding)
            if norm == 0:  # degenerate output — skip
                continue
            faces.append(
                DetectedFace(
                    bbox=(x1, y1, x2 - x1, y2 - y1),
                    embedding=embedding / norm,
                    det_score=float(face.det_score),
                )
            )
        return faces

    def crop(self, image_bytes: bytes, bbox: tuple[int, int, int, int]) -> bytes:
        """JPEG crop of a bbox (used for review-board thumbnails)."""
        buf = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Could not decode image")
        x, y, w, h = bbox
        ok, encoded = cv2.imencode(".jpg", img[y : y + h, x : x + w])
        if not ok:
            raise ValueError("Could not encode crop")
        return encoded.tobytes()


@lru_cache
def get_face_engine() -> FaceEngine:
    """Process-wide singleton. First call loads ONNX models (seconds) —
    main.py warms it during lifespan so requests never pay that cost."""
    return FaceEngine()
