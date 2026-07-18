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
