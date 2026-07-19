"""Face-embedding and face-image queries, including pgvector similarity."""

import uuid

from sqlalchemy import delete, select

from app.models.face import FaceEmbedding, StudentFaceImage
from app.repositories.base import BaseRepository


class FaceImageRepository(BaseRepository[StudentFaceImage]):
    model = StudentFaceImage

    async def list_for_student(self, student_id: uuid.UUID) -> list[StudentFaceImage]:
        result = await self.session.execute(
            select(StudentFaceImage).where(StudentFaceImage.student_id == student_id)
        )
        return list(result.scalars().all())


class EmbeddingRepository(BaseRepository[FaceEmbedding]):
    model = FaceEmbedding

    async def count_for_student(self, student_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(FaceEmbedding.id).where(FaceEmbedding.student_id == student_id)
        )
        return len(result.scalars().all())

    async def delete_all_for_student(self, student_id: uuid.UUID) -> None:
        """Right-to-erasure: purge every embedding for a student."""
        await self.session.execute(
            delete(FaceEmbedding).where(FaceEmbedding.student_id == student_id)
        )

    async def match_against_students(
        self, embedding: list[float], student_ids: list[uuid.UUID], *, limit: int = 5
    ) -> list[tuple[uuid.UUID, float]]:
        """ANN cosine match of a probe embedding against a set of students
        (the class gallery). Returns [(student_id, similarity)] best-first,
        at most one row per student (their best-matching enrollment photo).

        Embeddings are L2-normalized, so cosine_distance = 1 - similarity.
        Used by the attendance pipeline in Module 5.
        """
        if not student_ids:
            return []
        distance = FaceEmbedding.embedding.cosine_distance(embedding)
        stmt = (
            select(FaceEmbedding.student_id, distance.label("distance"))
            .where(FaceEmbedding.student_id.in_(student_ids))
            .order_by(distance)
            .limit(limit * 4)  # several embeddings per student; dedupe below
        )
        result = await self.session.execute(stmt)
        best: dict[uuid.UUID, float] = {}
        for student_id, dist in result.all():
            similarity = 1.0 - float(dist)
            if student_id not in best or similarity > best[student_id]:
                best[student_id] = similarity
        ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
        return ranked[:limit]
