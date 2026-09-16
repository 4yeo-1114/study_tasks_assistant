"""Create the initial tasks table.

Revision ID: 0001_initial_tasks
Revises:
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial_tasks"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("priority", sa.String(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'completed')",
            name="tasks_status_check",
        ),
        sa.CheckConstraint(
            "priority IN ('high', 'medium', 'low')",
            name="tasks_priority_check",
        ),
    )


def downgrade() -> None:
    op.drop_table("tasks")
