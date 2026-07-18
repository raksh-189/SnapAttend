"""Student CRUD endpoints. All authenticated users may read; any teacher or
admin may create/update (single-institution model — students are shared)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.common import Page
from app.schemas.student import StudentCreate, StudentOut, StudentUpdate
from app.services.student_service import StudentService

router = APIRouter(prefix="/students", tags=["students"])


@router.post("", response_model=StudentOut, status_code=status.HTTP_201_CREATED)
async def create_student(body: StudentCreate, user: CurrentUser, db: DbSession) -> StudentOut:
    return StudentOut.model_validate(await StudentService(db).create(body))


@router.get("", response_model=Page[StudentOut])
async def list_students(
    user: CurrentUser,
    db: DbSession,
    q: Annotated[str | None, Query(max_length=100, description="name/reg-number search")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[StudentOut]:
    items, total = await StudentService(db).search(query=q, offset=offset, limit=limit)
    return Page(
        items=[StudentOut.model_validate(s) for s in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{student_id}", response_model=StudentOut)
async def get_student(student_id: uuid.UUID, user: CurrentUser, db: DbSession) -> StudentOut:
    return StudentOut.model_validate(await StudentService(db).get(student_id))


@router.patch("/{student_id}", response_model=StudentOut)
async def update_student(
    student_id: uuid.UUID, body: StudentUpdate, user: CurrentUser, db: DbSession
) -> StudentOut:
    return StudentOut.model_validate(await StudentService(db).update(student_id, body))


@router.delete("/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_student(student_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    """Soft delete: attendance history survives. Biometric erasure is separate
    (Module 4)."""
    await StudentService(db).deactivate(student_id)
