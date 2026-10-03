"""add task proposal idempotency key

Revision ID: 0008_task_proposal_idempotency
Revises: 0007_document_lifecycle
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_task_proposal_idempotency"
down_revision = "0007_document_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("task_proposals") as batch_op:
        batch_op.add_column(
            sa.Column("idempotency_key", sa.String(length=128), nullable=True)
        )
        batch_op.create_unique_constraint(
            "uq_task_proposals_owner_idempotency_key",
            ["owner_id", "idempotency_key"],
        )


def downgrade() -> None:
    with op.batch_alter_table("task_proposals") as batch_op:
        batch_op.drop_constraint(
            "uq_task_proposals_owner_idempotency_key",
            type_="unique",
        )
        batch_op.drop_column("idempotency_key")
