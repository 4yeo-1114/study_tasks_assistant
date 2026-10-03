"""Store user-owned task proposals before any confirmed write."""

from alembic import op
import sqlalchemy as sa


revision = "0003_task_proposals"
down_revision = "0002_users_and_owners"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_proposals",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("priority", sa.String(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id"), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'rejected')",
            name="task_proposals_status_check",
        ),
    )
    op.create_index("ix_task_proposals_owner_id", "task_proposals", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_task_proposals_owner_id", table_name="task_proposals")
    op.drop_table("task_proposals")
