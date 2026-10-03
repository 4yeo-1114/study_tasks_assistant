"""add document lifecycle table

Revision ID: 0007_document_lifecycle
Revises: 0006_pgvector_hnsw
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_document_lifecycle"
down_revision = "0006_pgvector_hnsw"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("document_version", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("active_version", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id",
            "source",
            "document_version",
            name="uq_documents_owner_source_version",
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'processing', 'ready', 'failed', 'deleting', 'deleted')",
            name="documents_state_check",
        ),
    )
    op.create_index("ix_documents_owner_id", "documents", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_documents_owner_id", table_name="documents")
    op.drop_table("documents")
