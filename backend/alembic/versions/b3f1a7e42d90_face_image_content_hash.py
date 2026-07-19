"""face image content hash for duplicate detection

Revision ID: b3f1a7e42d90
Revises: 9a892bd1c01c
Create Date: 2026-07-19 09:05:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'b3f1a7e42d90'
down_revision: str | None = '9a892bd1c01c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Table is empty pre-Module-4, so a non-nullable add needs a server
    # default only long enough to backfill nothing; drop it right after.
    op.add_column(
        'student_face_images',
        sa.Column('content_hash', sa.String(length=64), nullable=False, server_default=''),
    )
    op.alter_column('student_face_images', 'content_hash', server_default=None)
    # Duplicate uploads (same student, same bytes) are rejected via this index.
    op.create_index(
        'uq_student_face_images_student_hash',
        'student_face_images',
        ['student_id', 'content_hash'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index('uq_student_face_images_student_hash', table_name='student_face_images')
    op.drop_column('student_face_images', 'content_hash')
