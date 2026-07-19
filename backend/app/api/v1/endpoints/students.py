"""Student CRUD endpoints. All authenticated users may read; any teacher or
admin may create/update (single-institution model — students are shared)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, UploadFile, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.common import Page
from app.schemas.student import (
    FaceEnrollmentBatchOut,
    FaceEnrollmentItemOut,
    FaceEnrollmentOut,
    FaceImageOut,
    StudentCreate,
    StudentOut,
    StudentUpdate,
)
from app.services.face.engine import FaceEngine, get_face_engine
from app.services.student_service import StudentService
from app.storage.local import LocalStorage, get_storage

router = APIRouter(prefix="/students", tags=["students"])

Engine = Annotated[FaceEngine, Depends(get_face_engine)]
Storage = Annotated[LocalStorage, Depends(get_storage)]


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


# --- Face enrollment -------------------------------------------------------


@router.post(
    "/{student_id}/face-images",
    response_model=FaceEnrollmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def enroll_face(
    student_id: uuid.UUID,
    file: UploadFile,
    user: CurrentUser,
    db: DbSession,
    engine: Engine,
    storage: Storage,
) -> FaceEnrollmentOut:
    """Upload one enrollment photo (JPEG/PNG, exactly one face). 3–5 photos
    per student recommended for robust matching."""
    data = await file.read()
    image, quality, total = await StudentService(db).enroll_face(
        student_id, data, engine=engine, storage=storage, uploaded_by=user.id
    )
    return FaceEnrollmentOut(
        image=FaceImageOut.model_validate(image),
        quality_score=quality,
        embeddings_total=total,
    )


@router.post(
    "/{student_id}/face-images/batch",
    response_model=FaceEnrollmentBatchOut,
    status_code=status.HTTP_207_MULTI_STATUS,
)
async def enroll_faces_batch(
    student_id: uuid.UUID,
    files: list[UploadFile],
    user: CurrentUser,
    db: DbSession,
    engine: Engine,
    storage: Storage,
) -> FaceEnrollmentBatchOut:
    """Upload several enrollment photos at once. Invalid files (bad format,
    no/multiple faces, exact duplicates, over the 5-photo cap) are skipped
    with a per-file reason; valid ones are enrolled. 207 because outcomes
    are mixed by design."""
    uploads = [(f.filename or "upload", await f.read()) for f in files]
    service = StudentService(db)
    results = await service.enroll_faces_batch(
        student_id, uploads, engine=engine, storage=storage, uploaded_by=user.id
    )
    items = [
        FaceEnrollmentItemOut(
            filename=r.filename,
            enrolled=r.image is not None,
            image=FaceImageOut.model_validate(r.image) if r.image else None,
            quality_score=r.quality_score,
            error=r.error,
        )
        for r in results
    ]
    enrolled = sum(1 for i in items if i.enrolled)
    totals = [r.embeddings_total for r in results if r.embeddings_total is not None]
    return FaceEnrollmentBatchOut(
        results=items,
        enrolled=enrolled,
        skipped=len(items) - enrolled,
        embeddings_total=totals[-1] if totals else await service.count_embeddings(student_id),
    )


@router.get("/{student_id}/face-images", response_model=list[FaceImageOut])
async def list_face_images(
    student_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> list[FaceImageOut]:
    rows = await StudentService(db).list_face_images(student_id)
    return [FaceImageOut.model_validate(r) for r in rows]


@router.delete(
    "/{student_id}/face-images/{image_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_face_image(
    student_id: uuid.UUID,
    image_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    storage: Storage,
) -> None:
    """Remove one enrollment photo and its embeddings."""
    await StudentService(db).delete_face_image(student_id, image_id, storage=storage)


@router.delete("/{student_id}/biometrics", status_code=status.HTTP_204_NO_CONTENT)
async def erase_biometrics(
    student_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    storage: Storage,
) -> None:
    """Right-to-erasure: purge ALL enrollment photos and embeddings for a
    student. The student record and attendance history remain."""
    await StudentService(db).erase_biometrics(student_id, storage=storage)
