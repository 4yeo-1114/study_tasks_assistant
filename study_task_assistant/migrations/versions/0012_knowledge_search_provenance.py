"""add document provenance and indexed keyword search columns

Revision ID: 0012_knowledge_search_provenance
Revises: 0011_fitness_imports
"""

from alembic import op

revision = "0012_knowledge_search_provenance"
down_revision = "0011_fitness_imports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS page_number INTEGER")
    op.execute("ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS search_tokens TEXT NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS search_vector tsvector GENERATED ALWAYS AS (to_tsvector('simple', search_tokens)) STORED")
    op.execute("CREATE INDEX IF NOT EXISTS ix_document_chunks_search_vector ON document_chunks USING gin (search_vector)")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_search_vector")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS search_vector")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS search_tokens")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS page_number")
