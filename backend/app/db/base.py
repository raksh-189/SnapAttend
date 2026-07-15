"""Declarative base and model registry.

Alembic autogenerate discovers tables through this module: importing
`app.db.base` imports every model exactly once.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UpdatedAtMixin:
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# Import all models so Base.metadata is complete (used by Alembic).
from app.models.audit import AuditLog  # noqa: E402,F401
from app.models.attendance import (  # noqa: E402,F401
    AttendanceRecord,
    AttendanceSession,
    FaceDetection,
    SessionImage,
)
from app.models.classroom import Classroom, Enrollment  # noqa: E402,F401
from app.models.face import FaceEmbedding, StudentFaceImage  # noqa: E402,F401
from app.models.student import Student  # noqa: E402,F401
from app.models.user import RefreshToken, User  # noqa: E402,F401
