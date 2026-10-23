"""add adjustment provenance to weekly plans

Revision ID: 0016_plan_adjustments
Revises: 0015_weekly_plans
"""

from alembic import op
import sqlalchemy as sa


revision = "0016_plan_adjustments"
down_revision = "0015_weekly_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("weekly_plans", sa.Column("plan_kind", sa.String(), nullable=False, server_default="weekly"))
    op.add_column("weekly_plans", sa.Column("source_plan_id", sa.String(length=32), nullable=True))
    op.add_column("weekly_plans", sa.Column("adjustment_summary", sa.String(length=2000), nullable=True))


def downgrade() -> None:
    op.drop_column("weekly_plans", "adjustment_summary")
    op.drop_column("weekly_plans", "source_plan_id")
    op.drop_column("weekly_plans", "plan_kind")
