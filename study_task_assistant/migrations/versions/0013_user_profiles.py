"""add explicit user profiles

Revision ID: 0013_user_profiles
Revises: 0012_knowledge_search_provenance
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_user_profiles"
down_revision = "0012_knowledge_search_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("learning_goal", sa.String(length=500), nullable=True),
        sa.Column("training_days_per_week", sa.Integer(), nullable=True),
        sa.Column("preferences", sa.String(length=2_000), nullable=True),
        sa.Column("limitations", sa.String(length=2_000), nullable=True),
        sa.Column("daily_minutes", sa.Integer(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "training_days_per_week IS NULL OR training_days_per_week BETWEEN 0 AND 7",
            name="user_profiles_training_days_range",
        ),
        sa.CheckConstraint(
            "daily_minutes IS NULL OR daily_minutes BETWEEN 1 AND 1440",
            name="user_profiles_daily_minutes_range",
        ),
        sa.UniqueConstraint("owner_id", name="uq_user_profiles_owner_id"),
    )
    op.create_index("ix_user_profiles_owner_id", "user_profiles", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_user_profiles_owner_id", table_name="user_profiles")
    op.drop_table("user_profiles")
