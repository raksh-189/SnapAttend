"""Attendance session, detection, and record queries."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.attendance import (
    AttendanceRecord,
    AttendanceSession,
    FaceDetection,
    SessionImage,
)
from app.repositories.base import BaseRepository


class AttendanceRepository(BaseRepository[AttendanceSession]):
    model = AttendanceSession

    async def get_with_details(self, session_id: uuid.UUID) -> AttendanceSession | None:
        """Session with images → detections and records eagerly loaded
        (everything the review board needs, no lazy-load surprises)."""
        result = await self.session.execute(
            select(AttendanceSession)
            .where(AttendanceSession.id == session_id)
            .options(
                selectinload(AttendanceSession.images).selectinload(SessionImage.detections),
                selectinload(AttendanceSession.records),
            )
        )
        return result.scalar_one_or_none()

    async def list_for_class(
        self, class_id: uuid.UUID, *, offset: int = 0, limit: int = 50
    ) -> tuple[list[AttendanceSession], int]:
        from sqlalchemy import func

        base = select(AttendanceSession).where(AttendanceSession.class_id == class_id)
        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))
        result = await self.session.execute(
            base.order_by(AttendanceSession.created_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), int(total or 0)

    async def get_record(
        self, session_id: uuid.UUID, student_id: uuid.UUID
    ) -> AttendanceRecord | None:
        result = await self.session.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.session_id == session_id,
                AttendanceRecord.student_id == student_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_detection(self, detection_id: uuid.UUID) -> FaceDetection | None:
        """Detection with its parent image loaded (to verify session ownership)."""
        result = await self.session.execute(
            select(FaceDetection)
            .where(FaceDetection.id == detection_id)
            .options(selectinload(FaceDetection.session_image))
        )
        return result.scalar_one_or_none()
