"""Face enrollment models: uploaded reference photos and their embeddings."""

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

EMBEDDING_DIM = 512  # ArcFace output dimension


class StudentFaceImage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "student_face_images"
    __table_args__ = (
        # One row per distinct photo per student — duplicate uploads are
        # detected by SHA-256 of the raw bytes.
        Index(
            "uq_student_face_images_student_hash",
            "student_id",
            "content_hash",
            unique=True,
        ),
    )

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    image_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )

    embeddings: Mapped[list["FaceEmbedding"]] = relationship(
        back_populates="source_image", cascade="all, delete-orphan", passive_deletes=True
    )


class FaceEmbedding(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "face_embeddings"
    __table_args__ = (
        # ANN cosine search over enrollment embeddings (L2-normalized).
        Index(
            "ix_face_embeddings_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

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
