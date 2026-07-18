"""Class CRUD and enrollment management.

Ownership contract (enforced here, never in routers): teachers may only
read or modify classes they own; admins may touch any class.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.models.classroom import Classroom, Enrollment
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.class_repo import ClassRepository
from app.repositories.student_repo import StudentRepository
from app.repositories.user_repo import UserRepository
from app.schemas.classroom import ClassCreate, ClassUpdate


class ClassService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.classes = ClassRepository(session)
        self.students = StudentRepository(session)
        self.users = UserRepository(session)

    async def create(self, data: ClassCreate, actor: User) -> Classroom:
        if await self.classes.get_by_code(data.code) is not None:
            raise ConflictError(f"Class with code {data.code!r} already exists")

        # Teachers own what they create; admins may assign any teacher.
        if actor.role == UserRole.ADMIN and data.teacher_id is not None:
            teacher = await self.users.get(data.teacher_id)
            if teacher is None or not teacher.is_active:
                raise NotFoundError("Teacher not found")
            teacher_id = teacher.id
        else:
            teacher_id = actor.id

        classroom = Classroom(
            code=data.code, name=data.name, room_type=data.room_type, teacher_id=teacher_id
        )
        self.classes.add(classroom)
        await self.session.commit()
        await self.session.refresh(classroom)
        return classroom

    async def get_owned(self, class_id: uuid.UUID, actor: User) -> Classroom:
        """Fetch a class the actor is allowed to touch — the ownership guard
        every class-scoped operation (incl. attendance, Module 5+) goes through."""
        classroom = await self.classes.get(class_id)
        if classroom is None:
            raise NotFoundError("Class not found")
        if actor.role != UserRole.ADMIN and classroom.teacher_id != actor.id:
            raise PermissionDeniedError("You do not own this class")
        return classroom

    async def list_classes(
        self, actor: User, *, offset: int, limit: int
    ) -> tuple[list[Classroom], int]:
        teacher_id = None if actor.role == UserRole.ADMIN else actor.id
        return await self.classes.list_for_teacher(teacher_id, offset=offset, limit=limit)

    async def update(self, class_id: uuid.UUID, data: ClassUpdate, actor: User) -> Classroom:
        classroom = await self.get_owned(class_id, actor)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(classroom, field, value)
        await self.session.commit()
        await self.session.refresh(classroom)
        return classroom

    async def deactivate(self, class_id: uuid.UUID, actor: User) -> None:
        classroom = await self.get_owned(class_id, actor)
        classroom.is_active = False
        await self.session.commit()

    # --- Enrollments -------------------------------------------------------

    async def roster(self, class_id: uuid.UUID, actor: User) -> list[Enrollment]:
        await self.get_owned(class_id, actor)
        return await self.classes.list_enrollments(class_id)

    async def enroll(
        self, class_id: uuid.UUID, student_ids: list[uuid.UUID], actor: User
    ) -> list[Enrollment]:
        """Idempotent bulk enroll: already-enrolled students are skipped."""
        await self.get_owned(class_id, actor)

        found = await self.students.get_many(student_ids)
        missing = set(student_ids) - {s.id for s in found}
        if missing:
            raise NotFoundError(f"Students not found: {', '.join(str(m) for m in missing)}")
        inactive = [s for s in found if not s.is_active]
        if inactive:
            raise ConflictError(
                "Cannot enroll inactive students: "
                + ", ".join(s.reg_number for s in inactive)
            )

        already = await self.classes.enrolled_student_ids(class_id)
        for student_id in student_ids:
            if student_id not in already:
                self.classes.add_enrollment(class_id, student_id)
        await self.session.commit()
        return await self.classes.list_enrollments(class_id)

    async def unenroll(self, class_id: uuid.UUID, student_id: uuid.UUID, actor: User) -> None:
        await self.get_owned(class_id, actor)
        enrollment = await self.classes.get_enrollment(class_id, student_id)
        if enrollment is None:
            raise NotFoundError("Student is not enrolled in this class")
        await self.session.delete(enrollment)
        await self.session.commit()
