"""add weekly plan proposals and profile plan version

Revision ID: 0015_weekly_plans
Revises: 0014_agent_sessions
"""

from alembic import op
import sqlalchemy as sa


revision = "0015_weekly_plans"
down_revision = "0014_agent_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_profiles", sa.Column("plan_version", sa.Integer(), nullable=False, server_default="0"))
    op.create_table(
        "weekly_plans",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("expected_profile_revision", sa.Integer(), nullable=False),
        sa.Column("base_plan_version", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("task_snapshot", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=True),
        sa.Column("task_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'confirmed', 'rejected')", name="weekly_plans_status_check"),
        sa.UniqueConstraint("owner_id", "idempotency_key", name="uq_weekly_plans_owner_idempotency_key"),
    )
    op.create_index("ix_weekly_plans_owner_id", "weekly_plans", ["owner_id"])
    op.create_index("ix_weekly_plans_week_start", "weekly_plans", ["week_start"])


def downgrade() -> None:
    op.drop_index("ix_weekly_plans_week_start", table_name="weekly_plans")
    op.drop_index("ix_weekly_plans_owner_id", table_name="weekly_plans")
    op.drop_table("weekly_plans")
    op.drop_column("user_profiles", "plan_version")
