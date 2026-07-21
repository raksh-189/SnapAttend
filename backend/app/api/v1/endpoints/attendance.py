"""Attendance endpoints: upload session photos, poll status, review board.

POST returns 202 immediately; the face pipeline runs as a BackgroundTask.
The frontend polls GET /sessions/{id} until status leaves `processing`.
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.deps import CurrentUser, DbSession
from app.db.session import get_session_factory
from app.schemas.attendance import (
    SessionCreateOut,
    SessionDetailOut,
    SessionSummaryOut,
)
from app.schemas.common import Page
from app.services.attendance_service import AttendanceService
from app.services.face import pipeline
from app.services.face.engine import FaceEngine, get_face_engine
from app.storage.local import LocalStorage, get_storage

router = APIRouter(prefix="/attendance", tags=["attendance"])

Engine = Annotated[FaceEngine, Depends(get_face_engine)]
Storage = Annotated[LocalStorage, Depends(get_storage)]
SessionFactory = Annotated[async_sessionmaker, Depends(get_session_factory)]


@router.post(
    "/sessions",
    response_model=SessionCreateOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_session(
    class_id: Annotated[uuid.UUID, Form()],
    session_date: Annotated[date, Form()],
    files: list[UploadFile],
    background: BackgroundTasks,
    user: CurrentUser,
    db: DbSession,
    engine: Engine,
    storage: Storage,
    session_factory: SessionFactory,
    period_label: Annotated[str | None, Form(max_length=64)] = None,
) -> SessionCreateOut:
    """Upload 1–5 classroom photos for a class you own. Returns 202 with the
    session id; poll GET /attendance/sessions/{id} until `pending_review`."""
    images = [await f.read() for f in files]
    session = await AttendanceService(db).create_session(
        class_id=class_id,
        session_date=session_date,
        period_label=period_label,
        images=images,
        actor=user,
        storage=storage,
    )
    # Enqueued after the service committed — the task will see the row.
    background.add_task(
        pipeline.process_session,
        session.id,
        engine=engine,
        storage=storage,
        session_factory=session_factory,
    )
    return SessionCreateOut(
        session_id=session.id, status=session.status, images_accepted=len(images)
    )


@router.get("/sessions/{session_id}", response_model=SessionDetailOut)
async def get_session(
    session_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> SessionDetailOut:
    """Session status + full review-board payload (evidence and draft
    verdicts are empty while still `processing`)."""
    return await AttendanceService(db).get_detail(session_id, user)


@router.get("/classes/{class_id}/sessions", response_model=Page[SessionSummaryOut])
async def list_class_sessions(
    class_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[SessionSummaryOut]:
    items, total = await AttendanceService(db).list_for_class(
        class_id, user, offset=offset, limit=limit
    )
    return Page(
        items=[SessionSummaryOut.model_validate(s) for s in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/sessions/{session_id}/detections/{detection_id}/crop")
async def get_detection_crop(
    session_id: uuid.UUID,
    detection_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    storage: Storage,
) -> Response:
    """Face-crop thumbnail for the review board."""
    data = await AttendanceService(db).get_crop(
        session_id, detection_id, user, storage=storage
    )
    return Response(content=data, media_type="image/jpeg")
