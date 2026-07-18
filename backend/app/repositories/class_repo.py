"""Classroom and enrollment queries."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.classroom import Classroom, Enrollment
from app.repositories.base import BaseRepository


class ClassRepository(BaseRepository[Classroom]):
    model = Classroom

    async def get_by_code(self, code: str) -> Classroom | None:
        result = await self.session.execute(select(Classroom).where(Classroom.code == code))
        return result.scalar_one_or_none()

    async def list_for_teacher(
        self, teacher_id: uuid.UUID | None, *, offset: int = 0, limit: int = 100
    ) -> tuple[list[Classroom], int]:
        """Paged classes. teacher_id=None lists all (admin view)."""
        stmt = select(Classroom)
        if teacher_id is not None:
            stmt = stmt.where(Classroom.teacher_id == teacher_id)
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery()))
        result = await self.session.execute(
            stmt.order_by(Classroom.code).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), int(total or 0)

    async def list_enrollments(self, class_id: uuid.UUID) -> list[Enrollment]:
        """Roster: enrollments with their students eagerly loaded."""
        result = await self.session.execute(
            select(Enrollment)
            .where(Enrollment.class_id == class_id)
            .options(selectinload(Enrollment.student))
        )
        return list(result.scalars().all())

    async def enrolled_student_ids(self, class_id: uuid.UUID) -> set[uuid.UUID]:
        result = await self.session.execute(
            select(Enrollment.student_id).where(Enrollment.class_id == class_id)
        )
        return set(result.scalars().all())

    def add_enrollment(self, class_id: uuid.UUID, student_id: uuid.UUID) -> Enrollment:
        enrollment = Enrollment(class_id=class_id, student_id=student_id)
        self.session.add(enrollment)
        return enrollment

    async def get_enrollment(
        self, class_id: uuid.UUID, student_id: uuid.UUID
    ) -> Enrollment | None:
        result = await self.session.execute(
            select(Enrollment).where(
                Enrollment.class_id == class_id, Enrollment.student_id == student_id
            )
        )
        return result.scalar_one_or_none()
