"""Model registry — importing this package registers every table on
Base.metadata exactly once (relied on by Alembic autogenerate and tests)."""

from app.models.attendance import (
    AttendanceRecord,
    AttendanceSession,
    FaceDetection,
    SessionImage,
)
from app.models.audit import AuditLog
from app.models.classroom import Classroom, Enrollment
from app.models.face import FaceEmbedding, StudentFaceImage
from app.models.student import Student
from app.models.user import RefreshToken, User

__all__ = [
    "AttendanceRecord",
    "AttendanceSession",
    "AuditLog",
    "Classroom",
    "Enrollment",
    "FaceDetection",
    "FaceEmbedding",
    "RefreshToken",
    "SessionImage",
    "Student",
    "StudentFaceImage",
    "User",
]
