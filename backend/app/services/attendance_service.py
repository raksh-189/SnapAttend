"""Attendance workflow: session state machine, review, verification.

Ownership: every operation goes through ClassService.get_owned — teachers
touch only their classes' sessions; admins any. The pipeline itself runs as
a BackgroundTask after `create_session` returns (see services/face/pipeline).
"""

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationFailedError
from app.core.logging import get_logger
from app.models.attendance import AttendanceSession, SessionImage
from app.models.enums import SessionStatus
from app.models.user import User
from app.repositories.attendance_repo import AttendanceRepository
from app.repositories.student_repo import StudentRepository
from app.schemas.attendance import (
    DetectionOut,
    RecordOut,
    RecordStudentOut,
    SessionDetailOut,
    SessionImageOut,
    SessionSummaryOut,
)
from app.services.class_service import ClassService
from app.services.student_service import validate_image_upload
from app.storage.base import StorageAdapter

logger = get_logger(__name__)

MIN_SESSION_IMAGES = 1
MAX_SESSION_IMAGES = 5


class AttendanceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.sessions = AttendanceRepository(session)
        self.classes = ClassService(session)

    async def create_session(
        self,
        *,
        class_id: uuid.UUID,
        session_date: date,
        period_label: str | None,
        images: list[bytes],
        actor: User,
        storage: StorageAdapter,
    ) -> AttendanceSession:
        """Validate + store the classroom photos and create a `processing`
        session. The caller enqueues the pipeline AFTER commit — never inside
        it — so the background task always sees the committed row."""
        classroom = await self.classes.get_owned(class_id, actor)
        if not (MIN_SESSION_IMAGES <= len(images) <= MAX_SESSION_IMAGES):
            raise ValidationFailedError(
                f"Provide between {MIN_SESSION_IMAGES} and {MAX_SESSION_IMAGES} images"
            )
        # Validate ALL images before storing ANY — reject the batch atomically.
        exts = [validate_image_upload(data) for data in images]

        session = AttendanceSession(
            class_id=classroom.id,
            teacher_id=actor.id,
            session_date=session_date,
            period_label=period_label,
            status=SessionStatus.PROCESSING,
        )
        self.sessions.add(session)
        await self.session.flush()  # session.id for keys + rows below

        saved_keys: list[str] = []
        try:
            for data, ext in zip(images, exts):
                key = f"sessions/{session.id}/{uuid.uuid4()}.{ext}"
                storage.save(key, data)
                saved_keys.append(key)
                self.session.add(SessionImage(session_id=session.id, image_path=key))
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            for key in saved_keys:  # don't leave orphaned files
                storage.delete(key)
            raise
        await self.session.refresh(session)
        logger.info(
            "session_created",
            session_id=str(session.id),
            class_id=str(class_id),
            images=len(images),
        )
        return session

    async def get_session_owned(
        self, session_id: uuid.UUID, actor: User
    ) -> AttendanceSession:
        session = await self.sessions.get_with_details(session_id)
        if session is None:
            raise NotFoundError("Session not found")
        await self.classes.get_owned(session.class_id, actor)  # 403 for non-owners
        return session

    async def get_detail(self, session_id: uuid.UUID, actor: User) -> SessionDetailOut:
        """Everything the review board renders in one response."""
        session = await self.get_session_owned(session_id, actor)

        student_ids = {r.student_id for r in session.records}
        students = await StudentRepository(self.session).get_many(list(student_ids))
        by_id = {s.id: s for s in students}

        return SessionDetailOut(
            session=SessionSummaryOut.model_validate(session),
            images=[
                SessionImageOut(
                    id=img.id,
                    faces_detected=img.faces_detected,
                    detections=[DetectionOut.model_validate(d) for d in img.detections],
                )
                for img in session.images
            ],
            records=sorted(
                (
                    RecordOut(
                        id=r.id,
                        student=RecordStudentOut.model_validate(by_id[r.student_id]),
                        status=r.status,
                        source=r.source,
                        confidence=r.confidence,
                        detection_id=r.detection_id,
                    )
                    for r in session.records
                    if r.student_id in by_id
                ),
                key=lambda r: r.student.reg_number,
            ),
        )

    async def list_for_class(
        self, class_id: uuid.UUID, actor: User, *, offset: int, limit: int
    ) -> tuple[list[AttendanceSession], int]:
        await self.classes.get_owned(class_id, actor)
        return await self.sessions.list_for_class(class_id, offset=offset, limit=limit)

    async def get_crop(
        self, session_id: uuid.UUID, detection_id: uuid.UUID, actor: User, *, storage: StorageAdapter
    ) -> bytes:
        """Face-crop thumbnail for the review board (auth + ownership checked)."""
        session = await self.get_session_owned(session_id, actor)
        detection = await self.sessions.get_detection(detection_id)
        if detection is None or detection.session_image.session_id != session.id:
            raise NotFoundError("Detection not found")
        try:
            return storage.get(detection.crop_path)
        except FileNotFoundError:
            raise NotFoundError("Crop image not found") from None
