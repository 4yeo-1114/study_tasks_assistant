"""Add optional learning/fitness task activity fields.

Revision ID: 0009_task_activity_fields
Revises: 0008_task_proposal_idempotency
"""

from alembic import op
import sqlalchemy as sa

revision = "0009_task_activity_fields"
down_revision = "0008_task_proposal_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tasks", schema=None) as batch:
        batch.add_column(sa.Column("task_type", sa.String(), nullable=True))
        batch.add_column(sa.Column("estimated_minutes", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("actual_minutes", sa.Integer(), nullable=True))
        batch.create_check_constraint(
            "tasks_task_type_check",
            "task_type IS NULL OR task_type IN ('learning', 'fitness')",
        )
        batch.create_check_constraint(
            "tasks_estimated_minutes_check",
            "estimated_minutes IS NULL OR estimated_minutes > 0",
        )
        batch.create_check_constraint(
            "tasks_actual_minutes_check",
            "actual_minutes IS NULL OR actual_minutes > 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("tasks", schema=None) as batch:
        batch.drop_constraint("tasks_actual_minutes_check", type_="check")
        batch.drop_constraint("tasks_estimated_minutes_check", type_="check")
        batch.drop_constraint("tasks_task_type_check", type_="check")
        batch.drop_column("actual_minutes")
        batch.drop_column("estimated_minutes")
        batch.drop_column("task_type")
