"""Attendance session request/response schemas.

The session detail response is everything the review board renders:
records (the draft verdict), detections grouped by image (the evidence),
and unknown faces awaiting teacher resolution.
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    AttendanceStatus,
    MatchStatus,
    RecordSource,
    SessionStatus,
)


class SessionCreateOut(BaseModel):
    """202 body: poll GET /sessions/{id} until it leaves `processing`."""

    session_id: uuid.UUID
    status: SessionStatus
    images_accepted: int


class SessionSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    class_id: uuid.UUID
    teacher_id: uuid.UUID
    session_date: date
    period_label: str | None
    status: SessionStatus
    error_message: str | None
    created_at: datetime
    confirmed_at: datetime | None


class DetectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_image_id: uuid.UUID
    bbox: dict
    matched_student_id: uuid.UUID | None
    confidence: float | None
    match_status: MatchStatus
    resolved_student_id: uuid.UUID | None


class SessionImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    faces_detected: int
    detections: list[DetectionOut]


class RecordStudentOut(BaseModel):
    """Roster identity embedded in each record — the board never joins
    client-side."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reg_number: str
    full_name: str


class RecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    student: RecordStudentOut
    status: AttendanceStatus
    source: RecordSource
    confidence: float | None
    detection_id: uuid.UUID | None


class SessionDetailOut(BaseModel):
    """Review board payload: summary + evidence + draft verdicts."""

    session: SessionSummaryOut
    images: list[SessionImageOut]
    records: list[RecordOut]


class RecordOverrideIn(BaseModel):
    """Teacher override of one student's draft verdict."""

    status: AttendanceStatus


class ResolveDetectionIn(BaseModel):
    """Assign an unknown face to a student (or clear a wrong assignment)."""

    student_id: uuid.UUID | None = None
    mark_present: bool = Field(
        default=True, description="Also flip the student's record to present"
    )
