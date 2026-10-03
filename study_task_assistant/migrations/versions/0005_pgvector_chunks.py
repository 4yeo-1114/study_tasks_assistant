"""add PostgreSQL vector document chunks

Revision ID: 0005_pgvector_chunks
Revises: 0004_proposal_task_history
"""

from alembic import op

revision = "0005_pgvector_chunks"
down_revision = "0004_proposal_task_history"
branch_labels = None
depends_on = None

EMBEDDING_DIMENSION = 512


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite remains usable for the existing local test suite.
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS document_chunks (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            owner_id BIGINT NOT NULL REFERENCES users(id),
            source TEXT NOT NULL,
            chunk_id INTEGER NOT NULL CHECK (chunk_id > 0),
            content TEXT NOT NULL CHECK (btrim(content) <> ''),
            embedding vector({EMBEDDING_DIMENSION}) NOT NULL,
            embedding_model TEXT NOT NULL,
            embedding_dimension INTEGER NOT NULL
                CHECK (embedding_dimension = {EMBEDDING_DIMENSION}),
            document_version TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (owner_id, source, chunk_id, document_version)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_owner_id "
        "ON document_chunks (owner_id)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_owner_id")
    op.execute("DROP TABLE IF EXISTS document_chunks")
    # Do not drop the shared extension: another table or service may use it.
