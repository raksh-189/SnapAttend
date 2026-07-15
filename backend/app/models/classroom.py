"""Classroom and enrollment models."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import RoomType
from app.models.student import Student


class Classroom(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A class/course taught by one teacher. Named Classroom to avoid the
    Python keyword; the table keeps the domain name `classes`."""

    __tablename__ = "classes"

    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True, nullable=False
    )
    room_type: Mapped[RoomType] = mapped_column(
        Enum(RoomType, name="room_type", values_callable=lambda e: [m.value for m in e]),
        default=RoomType.CLASSROOM,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    enrollments: Mapped[list["Enrollment"]] = relationship(
        back_populates="classroom", cascade="all, delete-orphan", passive_deletes=True
    )


class Enrollment(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("class_id", "student_id", name="uq_enrollment"),)

    class_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("classes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    classroom: Mapped[Classroom] = relationship(back_populates="enrollments")
    student: Mapped[Student] = relationship()
