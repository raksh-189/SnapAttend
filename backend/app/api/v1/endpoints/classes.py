"""Class CRUD and enrollment endpoints. Ownership is enforced in ClassService."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.classroom import (
    ClassCreate,
    ClassOut,
    ClassUpdate,
    EnrollmentOut,
    EnrollRequest,
)
from app.schemas.common import Page
from app.services.class_service import ClassService

router = APIRouter(prefix="/classes", tags=["classes"])


@router.post("", response_model=ClassOut, status_code=status.HTTP_201_CREATED)
async def create_class(body: ClassCreate, user: CurrentUser, db: DbSession) -> ClassOut:
    return ClassOut.model_validate(await ClassService(db).create(body, user))


@router.get("", response_model=Page[ClassOut])
async def list_classes(
    user: CurrentUser,
    db: DbSession,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[ClassOut]:
    items, total = await ClassService(db).list_classes(user, offset=offset, limit=limit)
    return Page(
        items=[ClassOut.model_validate(c) for c in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{class_id}", response_model=ClassOut)
async def get_class(class_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ClassOut:
    return ClassOut.model_validate(await ClassService(db).get_owned(class_id, user))


@router.patch("/{class_id}", response_model=ClassOut)
async def update_class(
    class_id: uuid.UUID, body: ClassUpdate, user: CurrentUser, db: DbSession
) -> ClassOut:
    return ClassOut.model_validate(await ClassService(db).update(class_id, body, user))


@router.delete("/{class_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_class(class_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    await ClassService(db).deactivate(class_id, user)


# --- Enrollments -----------------------------------------------------------


@router.get("/{class_id}/enrollments", response_model=list[EnrollmentOut])
async def roster(class_id: uuid.UUID, user: CurrentUser, db: DbSession) -> list[EnrollmentOut]:
    enrollments = await ClassService(db).roster(class_id, user)
    return [EnrollmentOut.model_validate(e) for e in enrollments]


@router.post("/{class_id}/enrollments", response_model=list[EnrollmentOut])
async def enroll(
    class_id: uuid.UUID, body: EnrollRequest, user: CurrentUser, db: DbSession
) -> list[EnrollmentOut]:
    """Bulk enroll; idempotent (already-enrolled students are skipped)."""
    enrollments = await ClassService(db).enroll(class_id, body.student_ids, user)
    return [EnrollmentOut.model_validate(e) for e in enrollments]


@router.delete(
    "/{class_id}/enrollments/{student_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def unenroll(
    class_id: uuid.UUID, student_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> None:
    await ClassService(db).unenroll(class_id, student_id, user)
