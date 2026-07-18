"""Student CRUD. Face enrollment (photo → embedding) lands here in Module 4."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.student import Student
from app.repositories.student_repo import StudentRepository
from app.schemas.student import StudentCreate, StudentUpdate


class StudentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.students = StudentRepository(session)

    async def create(self, data: StudentCreate) -> Student:
        if await self.students.get_by_reg_number(data.reg_number) is not None:
            raise ConflictError(f"Student with reg number {data.reg_number!r} already exists")
        student = Student(
            reg_number=data.reg_number,
            full_name=data.full_name,
            email=str(data.email).lower() if data.email else None,
        )
        self.students.add(student)
        await self.session.commit()
        await self.session.refresh(student)
        return student

    async def get(self, student_id: uuid.UUID) -> Student:
        student = await self.students.get(student_id)
        if student is None:
            raise NotFoundError("Student not found")
        return student

    async def search(
        self, *, query: str | None, offset: int, limit: int
    ) -> tuple[list[Student], int]:
        return await self.students.search(query=query, offset=offset, limit=limit)

    async def update(self, student_id: uuid.UUID, data: StudentUpdate) -> Student:
        student = await self.get(student_id)
        changes = data.model_dump(exclude_unset=True)
        if "email" in changes and changes["email"] is not None:
            changes["email"] = str(changes["email"]).lower()
        for field, value in changes.items():
            setattr(student, field, value)
        await self.session.commit()
        await self.session.refresh(student)
        return student

    async def deactivate(self, student_id: uuid.UUID) -> None:
        """Soft delete — history (attendance records) must survive.
        Right-to-erasure of biometric data is a separate endpoint (Module 4)."""
        student = await self.get(student_id)
        student.is_active = False
        await self.session.commit()
