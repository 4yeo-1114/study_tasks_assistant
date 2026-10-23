"""add persistent agent sessions, runs, and messages

Revision ID: 0014_agent_sessions
Revises: 0013_user_profiles
"""

from alembic import op
import sqlalchemy as sa


revision = "0014_agent_sessions"
down_revision = "0013_user_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('active', 'closed')", name="agent_sessions_status_check"),
    )
    op.create_index("ix_agent_sessions_owner_id", "agent_sessions", ["owner_id"])
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("session_id", sa.String(length=32), sa.ForeignKey("agent_sessions.id"), nullable=False),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error_type", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="agent_runs_status_check",
        ),
    )
    op.create_index("ix_agent_runs_session_id", "agent_runs", ["session_id"])
    op.create_index("ix_agent_runs_owner_id", "agent_runs", ["owner_id"])
    op.create_table(
        "agent_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.String(length=32), sa.ForeignKey("agent_sessions.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="agent_messages_role_check"),
        sa.UniqueConstraint("session_id", "sequence", name="uq_agent_messages_session_sequence"),
    )
    op.create_index("ix_agent_messages_session_id", "agent_messages", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_messages_session_id", table_name="agent_messages")
    op.drop_table("agent_messages")
    op.drop_index("ix_agent_runs_owner_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_session_id", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_agent_sessions_owner_id", table_name="agent_sessions")
    op.drop_table("agent_sessions")
