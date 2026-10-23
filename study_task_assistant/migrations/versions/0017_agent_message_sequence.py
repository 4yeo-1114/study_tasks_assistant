"""allocate conversation message sequences atomically

Revision ID: 0017_agent_message_sequence
Revises: 0016_plan_adjustments
"""

from alembic import op
import sqlalchemy as sa


revision = "0017_agent_message_sequence"
down_revision = "0016_plan_adjustments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_sessions",
        sa.Column("message_sequence", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(
        "UPDATE agent_sessions SET message_sequence = COALESCE("
        "(SELECT MAX(agent_messages.sequence) FROM agent_messages "
        "WHERE agent_messages.session_id = agent_sessions.id), 0)"
    )


def downgrade() -> None:
    op.drop_column("agent_sessions", "message_sequence")
