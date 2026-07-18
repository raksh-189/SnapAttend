"""Student queries."""

import uuid

from sqlalchemy import func, or_, select

from app.models.student import Student
from app.repositories.base import BaseRepository


class StudentRepository(BaseRepository[Student]):
    model = Student

    async def get_by_reg_number(self, reg_number: str) -> Student | None:
        result = await self.session.execute(
            select(Student).where(Student.reg_number == reg_number)
        )
        return result.scalar_one_or_none()

    async def search(
        self, *, query: str | None = None, offset: int = 0, limit: int = 100
    ) -> tuple[list[Student], int]:
        """Paged list with optional name/reg-number search. Returns (items, total)."""
        stmt = select(Student)
        if query:
            pattern = f"%{query}%"
            stmt = stmt.where(
                or_(Student.full_name.ilike(pattern), Student.reg_number.ilike(pattern))
            )
        total = await self.session.scalar(
            select(func.count()).select_from(stmt.subquery())
        )
        result = await self.session.execute(
            stmt.order_by(Student.reg_number).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), int(total or 0)

    async def get_many(self, student_ids: list[uuid.UUID]) -> list[Student]:
        result = await self.session.execute(
            select(Student).where(Student.id.in_(student_ids))
        )
        return list(result.scalars().all())
