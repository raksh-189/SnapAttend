"""Multi-image attendance pipeline: detect → embed → match → dedupe → drafts.

Runs as a FastAPI BackgroundTask *after* the upload request returns 202, so
it owns its own DB session (the request's session is already closed). The
entry point is plain-Python and queue-agnostic — a Celery task could call
`process_session` unchanged.
"""

import asyncio
import uuid

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import async_session_factory
from app.models.attendance import AttendanceRecord, AttendanceSession, FaceDetection
from app.models.enums import (
    AttendanceStatus,
    MatchStatus,
    RecordSource,
    SessionStatus,
)
from app.repositories.attendance_repo import AttendanceRepository
from app.repositories.class_repo import ClassRepository
from app.repositories.embedding_repo import EmbeddingRepository
from app.services.face.engine import FaceEngine
from app.services.face.matcher import classify_face, dedupe_across_images
from app.storage.base import StorageAdapter

logger = get_logger(__name__)


async def process_session(
    session_id: uuid.UUID,
    *,
    engine: FaceEngine,
    storage: StorageAdapter,
    session_factory=None,
) -> None:
    """Process every image of a `processing` session into detections and
    draft attendance records, then move it to `pending_review`.

    Runs after the upload request's session is closed, so it opens its own
    (`session_factory` is injectable for tests). Any unexpected failure marks
    the session `failed` with a message — the teacher retries with a new
    session; nothing is half-committed.
    """
    factory = session_factory or async_session_factory
    async with factory() as db:
        sessions = AttendanceRepository(db)
        session = await sessions.get_with_details(session_id)
        if session is None or session.status is not SessionStatus.PROCESSING:
            logger.warning("pipeline_skip", session_id=str(session_id))
            return
        try:
            await _run(db, session, engine=engine, storage=storage)
        except Exception as exc:
            logger.exception("pipeline_failed", session_id=str(session_id))
            await db.rollback()
            # Re-fetch on the clean session: mark failed so polling terminates.
            session = await sessions.get(session_id)
            if session is not None:
                session.status = SessionStatus.FAILED
                session.error_message = f"Processing failed: {exc}"
                await db.commit()


async def _run(
    db, session: AttendanceSession, *, engine: FaceEngine, storage: StorageAdapter
) -> None:
    settings = get_settings()
    threshold = settings.FACE_MATCH_THRESHOLD
    roster = await ClassRepository(db).enrolled_student_ids(session.class_id)
    embeddings = EmbeddingRepository(db)

    detections: list[FaceDetection] = []
    outcomes = []
    for image_index, image in enumerate(session.images):
        data = storage.get(image.image_path)
        # CPU-bound ONNX inference — off the event loop.
        faces = await asyncio.to_thread(engine.detect, data)
        image.faces_detected = len(faces)

        for face_index, face in enumerate(faces):
            candidates = await embeddings.match_against_students(
                face.embedding.tolist(), list(roster)
            )
            outcome = classify_face(
                face.det_score,
                candidates,
                image_index=image_index,
                face_index=face_index,
                threshold=threshold,
            )
            outcomes.append(outcome)

            crop_key = f"sessions/{session.id}/crops/{uuid.uuid4()}.jpg"
            crop = await asyncio.to_thread(engine.crop, data, face.bbox)
            storage.save(crop_key, crop)
            x, y, w, h = face.bbox
            detections.append(
                FaceDetection(
                    session_image_id=image.id,
                    bbox={"x": x, "y": y, "w": w, "h": h},
                    crop_path=crop_key,
                    match_status=outcome.status,  # finalized after dedupe
                )
            )

    # A student seen in several photos keeps one MATCHED detection
    # (highest confidence); the rest become DUPLICATE.
    dedupe_across_images(outcomes)
    for detection, outcome in zip(detections, outcomes):
        detection.match_status = outcome.status
        if outcome.status in (MatchStatus.MATCHED, MatchStatus.DUPLICATE):
            detection.matched_student_id = outcome.student_id
            detection.confidence = outcome.confidence
        db.add(detection)
    await db.flush()  # detection ids for the record FKs below

    # Draft verdicts: matched students present(ai), rest of roster absent(ai).
    present: dict[uuid.UUID, FaceDetection] = {}
    for detection, outcome in zip(detections, outcomes):
        if outcome.status is MatchStatus.MATCHED and outcome.student_id is not None:
            present[outcome.student_id] = detection
    for student_id in roster:
        detection = present.get(student_id)
        db.add(
            AttendanceRecord(
                session_id=session.id,
                student_id=student_id,
                status=AttendanceStatus.PRESENT if detection else AttendanceStatus.ABSENT,
                source=RecordSource.AI,
                confidence=detection.confidence if detection else None,
                detection_id=detection.id if detection else None,
            )
        )

    session.status = SessionStatus.PENDING_REVIEW
    await db.commit()
    logger.info(
        "pipeline_done",
        session_id=str(session.id),
        images=len(session.images),
        faces=len(detections),
        present=len(present),
        absent=len(roster) - len(present),
        unknown=sum(1 for o in outcomes if o.status is MatchStatus.UNKNOWN),
    )
