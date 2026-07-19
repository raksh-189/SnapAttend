"""Student request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class StudentCreate(BaseModel):
    reg_number: str = Field(min_length=1, max_length=64)
    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr | None = None


class StudentUpdate(BaseModel):
    """Partial update — omitted fields are left unchanged."""

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailStr | None = None
    is_active: bool | None = None


class StudentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reg_number: str
    full_name: str
    email: EmailStr | None
    is_active: bool
    created_at: datetime


class FaceImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    student_id: uuid.UUID
    created_at: datetime


class FaceEnrollmentOut(BaseModel):
    """Result of one enrollment photo upload."""

    image: FaceImageOut
    quality_score: float
    embeddings_total: int  # how many embeddings the student now has


class FaceEnrollmentItemOut(BaseModel):
    """Per-file outcome of a batch upload — enrolled or skipped with a reason."""

    filename: str
    enrolled: bool
    image: FaceImageOut | None = None
    quality_score: float | None = None
    error: str | None = None


class FaceEnrollmentBatchOut(BaseModel):
    """Result of a multi-photo enrollment upload."""

    results: list[FaceEnrollmentItemOut]
    enrolled: int
    skipped: int
    embeddings_total: int
