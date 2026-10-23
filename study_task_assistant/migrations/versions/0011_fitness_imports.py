"""Track idempotent fitness CSV imports.

Revision ID: 0011_fitness_imports
Revises: 0010_fitness_records
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_fitness_imports"
down_revision = "0010_fitness_records"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("fitness_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("import_key", sa.String(64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("workout_count", sa.Integer(), nullable=False),
        sa.Column("weight_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("owner_id", "import_key", name="uq_fitness_import_owner_key"),
    )
    op.create_index("ix_fitness_imports_owner_id", "fitness_imports", ["owner_id"])


def downgrade():
    op.drop_table("fitness_imports")
