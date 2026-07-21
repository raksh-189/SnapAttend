"""Attendance workflow: session state machine, review, verification.

Ownership: every operation goes through ClassService.get_owned — teachers
touch only their classes' sessions; admins any. The pipeline itself runs as
a BackgroundTask after `create_session` returns (see services/face/pipeline).
"""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidStateError, NotFoundError, ValidationFailedError
from app.core.logging import get_logger
from app.models.attendance import AttendanceRecord, AttendanceSession, SessionImage
from app.models.audit import AuditLog
from app.models.enums import AttendanceStatus, MatchStatus, RecordSource, SessionStatus
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

    # --- Verification (evidence → confirmed verdict) -------------------------

    @staticmethod
    def _require_reviewable(session: AttendanceSession) -> None:
        """Edits are only legal while the teacher is reviewing."""
        if session.status is not SessionStatus.PENDING_REVIEW:
            raise InvalidStateError(
                f"Session is {session.status.value}; edits require pending_review"
            )

    async def override_record(
        self,
        session_id: uuid.UUID,
        student_id: uuid.UUID,
        new_status: AttendanceStatus,
        actor: User,
    ) -> AttendanceRecord:
        """Teacher overrides one student's draft verdict (source → manual)."""
        session = await self.get_session_owned(session_id, actor)
        self._require_reviewable(session)
        record = await self.sessions.get_record(session_id, student_id)
        if record is None:
            raise NotFoundError("No attendance record for this student in this session")

        record.status = new_status
        record.source = RecordSource.MANUAL
        record.marked_by = actor.id
        self.session.add(
            AuditLog(
                user_id=actor.id,
                action="record.override",
                entity_type="attendance_record",
                entity_id=record.id,
                payload={"student_id": str(student_id), "status": new_status.value},
            )
        )
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def resolve_detection(
        self,
        session_id: uuid.UUID,
        detection_id: uuid.UUID,
        student_id: uuid.UUID | None,
        actor: User,
        *,
        mark_present: bool = True,
    ) -> None:
        """Assign an unknown/low-quality face to a roster student (or clear a
        previous assignment with student_id=None). Optionally flips the
        student's record to present(manual)."""
        session = await self.get_session_owned(session_id, actor)
        self._require_reviewable(session)
        detection = await self.sessions.get_detection(detection_id)
        if detection is None or detection.session_image.session_id != session.id:
            raise NotFoundError("Detection not found")
        if detection.match_status not in (MatchStatus.UNKNOWN, MatchStatus.LOW_QUALITY):
            raise InvalidStateError("Only unknown or low-quality faces can be resolved")

        if student_id is not None:
            record = await self.sessions.get_record(session_id, student_id)
            if record is None:  # not on this class's roster
                raise NotFoundError("Student has no record in this session")
            if mark_present:
                record.status = AttendanceStatus.PRESENT
                record.source = RecordSource.MANUAL
                record.marked_by = actor.id
                record.detection_id = detection.id
                record.confidence = None  # human call, not an AI score

        detection.resolved_student_id = student_id
        detection.resolved_by = actor.id if student_id is not None else None
        self.session.add(
            AuditLog(
                user_id=actor.id,
                action="detection.resolve",
                entity_type="face_detection",
                entity_id=detection.id,
                payload={
                    "student_id": str(student_id) if student_id else None,
                    "mark_present": mark_present,
                },
            )
        )
        await self.session.commit()

    async def confirm_session(self, session_id: uuid.UUID, actor: User) -> AttendanceSession:
        """pending_review → confirmed. Terminal: records become the official
        register and feed analytics/reports."""
        session = await self.get_session_owned(session_id, actor)
        self._require_reviewable(session)

        session.status = SessionStatus.CONFIRMED
        session.confirmed_at = datetime.now(timezone.utc)
        present = sum(
            1 for r in session.records if r.status is AttendanceStatus.PRESENT
        )
        self.session.add(
            AuditLog(
                user_id=actor.id,
                action="session.confirm",
                entity_type="attendance_session",
                entity_id=session.id,
                payload={"present": present, "total": len(session.records)},
            )
        )
        await self.session.commit()
        await self.session.refresh(session)
        logger.info(
            "session_confirmed",
            session_id=str(session.id),
            present=present,
            total=len(session.records),
        )
        return session
