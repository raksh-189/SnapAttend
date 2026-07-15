"""Attendance session, session images, face detections, and attendance records.

`FaceDetection` rows are AI *evidence* (one per face per image).
`AttendanceRecord` rows are the *verdict* (one per student per session).
Teacher verification turns evidence into confirmed verdicts.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UpdatedAtMixin, UUIDPrimaryKeyMixin
from app.models.enums import AttendanceStatus, MatchStatus, RecordSource, SessionStatus


class AttendanceSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "attendance_sessions"
    __table_args__ = (Index("ix_sessions_class_date", "class_id", "session_date"),)

    class_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("classes.id"), nullable=False
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    period_label: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus, name="session_status", values_callable=lambda e: [m.value for m in e]),
        default=SessionStatus.PROCESSING,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    images: Mapped[list["SessionImage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", passive_deletes=True
    )
    records: Mapped[list["AttendanceRecord"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", passive_deletes=True
    )


class SessionImage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "session_images"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    image_path: Mapped[str] = mapped_column(Text, nullable=False)
    faces_detected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    session: Mapped[AttendanceSession] = relationship(back_populates="images")
    detections: Mapped[list["FaceDetection"]] = relationship(
        back_populates="session_image", cascade="all, delete-orphan", passive_deletes=True
    )


class FaceDetection(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "face_detections"

    session_image_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("session_images.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    bbox: Mapped[dict] = mapped_column(JSONB, nullable=False)  # {x, y, w, h}
    crop_path: Mapped[str] = mapped_column(Text, nullable=False)
    matched_student_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id")
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    match_status: Mapped[MatchStatus] = mapped_column(
        Enum(MatchStatus, name="match_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    # Teacher resolution of an unknown face:
    resolved_student_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id")
    )
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    session_image: Mapped[SessionImage] = relationship(back_populates="detections")


class AttendanceRecord(Base, UUIDPrimaryKeyMixin, UpdatedAtMixin):
    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint("session_id", "student_id", name="uq_record_session_student"),
        Index("ix_records_student", "student_id"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id"), nullable=False
    )
    status: Mapped[AttendanceStatus] = mapped_column(
        Enum(
            AttendanceStatus,
            name="attendance_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    source: Mapped[RecordSource] = mapped_column(
        Enum(RecordSource, name="record_source", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    detection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("face_detections.id", ondelete="SET NULL")
    )
    marked_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    session: Mapped[AttendanceSession] = relationship(back_populates="records")
