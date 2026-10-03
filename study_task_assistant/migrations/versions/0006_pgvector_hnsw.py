"""add cosine HNSW index for document chunk vectors

Revision ID: 0006_pgvector_hnsw
Revises: 0005_pgvector_chunks
"""

from alembic import op

revision = "0006_pgvector_hnsw"
down_revision = "0005_pgvector_chunks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw
        ON document_chunks USING hnsw (embedding vector_cosine_ops)
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")
