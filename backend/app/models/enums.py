"""Domain enums, shared between ORM models and Pydantic schemas.

Stored in PostgreSQL as native ENUM types (names given in each model).
"""

import enum


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    TEACHER = "teacher"


class RoomType(str, enum.Enum):
    CLASSROOM = "classroom"
    LABORATORY = "laboratory"
    SEMINAR_HALL = "seminar_hall"


class SessionStatus(str, enum.Enum):
    PROCESSING = "processing"
    PENDING_REVIEW = "pending_review"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class MatchStatus(str, enum.Enum):
    MATCHED = "matched"
    DUPLICATE = "duplicate"
    UNKNOWN = "unknown"
    LOW_QUALITY = "low_quality"


class AttendanceStatus(str, enum.Enum):
    PRESENT = "present"
    ABSENT = "absent"
    LATE = "late"
    EXCUSED = "excused"


class RecordSource(str, enum.Enum):
    AI = "ai"
    MANUAL = "manual"
