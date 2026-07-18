"""Classroom and enrollment request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import RoomType
from app.schemas.student import StudentOut


class ClassCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    room_type: RoomType = RoomType.CLASSROOM
    teacher_id: uuid.UUID | None = None  # admin may assign; teachers get themselves


class ClassUpdate(BaseModel):
    """Partial update — omitted fields are left unchanged."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    room_type: RoomType | None = None
    is_active: bool | None = None


class ClassOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    teacher_id: uuid.UUID
    room_type: RoomType
    is_active: bool
    created_at: datetime


class EnrollRequest(BaseModel):
    student_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class EnrollmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    enrolled_at: datetime
    student: StudentOut
