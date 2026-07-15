"""Face enrollment models: uploaded reference photos and their embeddings."""

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

EMBEDDING_DIM = 512  # ArcFace output dimension


class StudentFaceImage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "student_face_images"

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    image_path: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )

    embeddings: Mapped[list["FaceEmbedding"]] = relationship(
        back_populates="source_image", cascade="all, delete-orphan", passive_deletes=True
    )


class FaceEmbedding(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "face_embeddings"

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    source_image_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("student_face_images.id", ondelete="CASCADE"),
        nullable=False,
    )
    # L2-normalized; cosine similarity == dot product. HNSW index in migration.
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    quality_score: Mapped[float | None] = mapped_column(Float)

    source_image: Mapped[StudentFaceImage] = relationship(back_populates="embeddings")
