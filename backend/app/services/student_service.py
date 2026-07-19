"""Student CRUD and face enrollment (photo → embedding)."""

import asyncio
import hashlib
import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import (
    ConflictError,
    DomainError,
    NotFoundError,
    ValidationFailedError,
)
from app.core.logging import get_logger
from app.models.face import FaceEmbedding, StudentFaceImage
from app.models.student import Student
from app.repositories.embedding_repo import EmbeddingRepository, FaceImageRepository
from app.repositories.student_repo import StudentRepository
from app.schemas.student import StudentCreate, StudentUpdate
from app.services.face.engine import FaceEngine
from app.storage.base import StorageAdapter

logger = get_logger(__name__)

# Magic-byte signatures for the only formats we accept.
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# Enrollment photos must contain exactly one clearly-detected face.
MIN_ENROLLMENT_DET_SCORE = 0.50
MAX_ENROLLMENT_PHOTOS = 5


@dataclass
class FaceEnrollmentItemResult:
    """Per-file outcome of a batch enrollment; exactly one of image/error set."""

    filename: str
    image: StudentFaceImage | None = None
    quality_score: float | None = None
    embeddings_total: int | None = None
    error: str | None = None


def validate_image_upload(data: bytes) -> str:
    """Magic-bytes + size validation. Returns the file extension."""
    max_bytes = get_settings().MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(data) > max_bytes:
        raise ValidationFailedError(
            f"Image exceeds the {get_settings().MAX_UPLOAD_SIZE_MB} MB limit"
        )
    if data.startswith(_JPEG_MAGIC):
        return "jpg"
    if data.startswith(_PNG_MAGIC):
        return "png"
    raise ValidationFailedError("Only JPEG or PNG images are accepted")


class StudentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.students = StudentRepository(session)

    async def create(self, data: StudentCreate) -> Student:
        if await self.students.get_by_reg_number(data.reg_number) is not None:
            raise ConflictError(f"Student with reg number {data.reg_number!r} already exists")
        student = Student(
            reg_number=data.reg_number,
            full_name=data.full_name,
            email=str(data.email).lower() if data.email else None,
        )
        self.students.add(student)
        await self.session.commit()
        await self.session.refresh(student)
        return student

    async def get(self, student_id: uuid.UUID) -> Student:
        student = await self.students.get(student_id)
        if student is None:
            raise NotFoundError("Student not found")
        return student

    async def search(
        self, *, query: str | None, offset: int, limit: int
    ) -> tuple[list[Student], int]:
        return await self.students.search(query=query, offset=offset, limit=limit)

    async def update(self, student_id: uuid.UUID, data: StudentUpdate) -> Student:
        student = await self.get(student_id)
        changes = data.model_dump(exclude_unset=True)
        if "email" in changes and changes["email"] is not None:
            changes["email"] = str(changes["email"]).lower()
        for field, value in changes.items():
            setattr(student, field, value)
        await self.session.commit()
        await self.session.refresh(student)
        return student

    async def deactivate(self, student_id: uuid.UUID) -> None:
        """Soft delete — history (attendance records) must survive.
        Right-to-erasure of biometric data is a separate endpoint (Module 4)."""
        student = await self.get(student_id)
        student.is_active = False
        await self.session.commit()

    # --- Face enrollment ---------------------------------------------------

    async def enroll_face(
        self,
        student_id: uuid.UUID,
        image_bytes: bytes,
        *,
        engine: FaceEngine,
        storage: StorageAdapter,
        uploaded_by: uuid.UUID | None,
    ) -> tuple[StudentFaceImage, float, int]:
        """One enrollment photo → stored image + one embedding.

        The photo must contain exactly one clearly-detected face.
        Returns (image_row, quality_score, total_embeddings_for_student).
        """
        student = await self.get(student_id)
        if not student.is_active:
            raise ConflictError("Cannot enroll faces for an inactive student")

        images = FaceImageRepository(self.session)
        embeddings = EmbeddingRepository(self.session)

        existing = await images.list_for_student(student_id)
        if len(existing) >= MAX_ENROLLMENT_PHOTOS:
            raise ConflictError(
                f"Student already has {MAX_ENROLLMENT_PHOTOS} enrollment photos"
            )

        ext = validate_image_upload(image_bytes)

        # Duplicate detection: same bytes for the same student is a re-upload,
        # not a new pose. (DB unique index on (student_id, content_hash) is the
        # race-proof backstop.)
        content_hash = hashlib.sha256(image_bytes).hexdigest()
        if any(r.content_hash == content_hash for r in existing):
            raise ConflictError("This exact image is already enrolled for the student")

        # CPU-bound inference — keep it off the event loop.
        try:
            faces = await asyncio.to_thread(engine.detect, image_bytes)
        except ValueError as exc:
            raise ValidationFailedError(str(exc)) from None
        faces = [f for f in faces if f.det_score >= MIN_ENROLLMENT_DET_SCORE]
        if len(faces) == 0:
            raise ValidationFailedError("No face detected — use a clear, frontal photo")
        if len(faces) > 1:
            raise ValidationFailedError(
                f"Found {len(faces)} faces — enrollment photos must contain exactly one"
            )
        face = faces[0]

        key = f"enrollment/{student_id}/{uuid.uuid4()}.{ext}"
        storage.save(key, image_bytes)

        image_row = StudentFaceImage(
            student_id=student_id,
            image_path=key,
            content_hash=content_hash,
            uploaded_by=uploaded_by,
        )
        self.session.add(image_row)
        await self.session.flush()  # image_row.id for the FK below

        self.session.add(
            FaceEmbedding(
                student_id=student_id,
                source_image_id=image_row.id,
                embedding=face.embedding.tolist(),
                model_name=engine.model_name,
                quality_score=face.det_score,
            )
        )
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            storage.delete(key)  # don't leave orphaned files
            raise ConflictError(
                "This exact image is already enrolled for the student"
            ) from None
        except Exception:
            await self.session.rollback()
            storage.delete(key)
            raise
        await self.session.refresh(image_row)

        total = await embeddings.count_for_student(student_id)
        logger.info(
            "face_enrolled",
            student_id=str(student_id),
            image_id=str(image_row.id),
            quality=round(face.det_score, 3),
            embeddings_total=total,
        )
        return image_row, face.det_score, total

    async def enroll_faces_batch(
        self,
        student_id: uuid.UUID,
        uploads: list[tuple[str, bytes]],
        *,
        engine: FaceEngine,
        storage: StorageAdapter,
        uploaded_by: uuid.UUID | None,
    ) -> list[FaceEnrollmentItemResult]:
        """Enroll several photos in one request.

        Each file is processed independently: invalid images (undecodable,
        wrong format, no/multiple faces, duplicates, over the photo cap) are
        SKIPPED and reported per-file, never failing the whole batch.
        """
        results: list[FaceEnrollmentItemResult] = []
        for filename, data in uploads:
            try:
                image_row, quality, total = await self.enroll_face(
                    student_id,
                    data,
                    engine=engine,
                    storage=storage,
                    uploaded_by=uploaded_by,
                )
            except NotFoundError:
                raise  # unknown student fails the request, not the file
            except DomainError as exc:
                logger.warning(
                    "face_enrollment_skipped",
                    student_id=str(student_id),
                    filename=filename,
                    reason=exc.detail,
                )
                results.append(
                    FaceEnrollmentItemResult(filename=filename, error=exc.detail)
                )
            else:
                results.append(
                    FaceEnrollmentItemResult(
                        filename=filename,
                        image=image_row,
                        quality_score=quality,
                        embeddings_total=total,
                    )
                )
        enrolled = sum(1 for r in results if r.image is not None)
        logger.info(
            "face_enrollment_batch_done",
            student_id=str(student_id),
            uploaded=len(uploads),
            enrolled=enrolled,
            skipped=len(uploads) - enrolled,
        )
        return results

    async def list_face_images(self, student_id: uuid.UUID) -> list[StudentFaceImage]:
        await self.get(student_id)  # 404 on unknown student
        return await FaceImageRepository(self.session).list_for_student(student_id)

    async def count_embeddings(self, student_id: uuid.UUID) -> int:
        return await EmbeddingRepository(self.session).count_for_student(student_id)

    async def delete_face_image(
        self, student_id: uuid.UUID, image_id: uuid.UUID, *, storage: StorageAdapter
    ) -> None:
        """Delete one enrollment photo + its embeddings (DB cascade)."""
        images = FaceImageRepository(self.session)
        image = await images.get(image_id)
        if image is None or image.student_id != student_id:
            raise NotFoundError("Face image not found")
        key = image.image_path
        await self.session.delete(image)
        await self.session.commit()
        storage.delete(key)

    async def erase_biometrics(self, student_id: uuid.UUID, *, storage: StorageAdapter) -> None:
        """Right-to-erasure: purge ALL enrollment photos and embeddings."""
        await self.get(student_id)
        images = FaceImageRepository(self.session)
        rows = await images.list_for_student(student_id)
        keys = [r.image_path for r in rows]
        for row in rows:
            await self.session.delete(row)  # embeddings cascade
        await EmbeddingRepository(self.session).delete_all_for_student(student_id)
        await self.session.commit()
        for key in keys:
            storage.delete(key)
        logger.info("biometrics_erased", student_id=str(student_id), photos=len(keys))
