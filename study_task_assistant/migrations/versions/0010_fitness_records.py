"""Add workout and body weight records.

Revision ID: 0010_fitness_records
Revises: 0009_task_activity_fields
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_fitness_records"
down_revision = "0009_task_activity_fields"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("workout_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("workout_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.String(), nullable=True),
    )
    op.create_index("ix_workout_sessions_owner_id", "workout_sessions", ["owner_id"])
    op.create_index("ix_workout_sessions_workout_date", "workout_sessions", ["workout_date"])
    op.create_table("exercise_sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("workout_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("exercise_name", sa.String(), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=False),
        sa.CheckConstraint("weight_kg > 0", name="exercise_sets_weight_check"),
        sa.CheckConstraint("reps > 0", name="exercise_sets_reps_check"),
    )
    op.create_index("ix_exercise_sets_session_id", "exercise_sets", ["session_id"])
    op.create_table("body_weight_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("recorded_on", sa.Date(), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=False),
        sa.UniqueConstraint("owner_id", "recorded_on", name="uq_body_weight_owner_date"),
        sa.CheckConstraint("weight_kg > 0", name="body_weight_positive_check"),
    )
    op.create_index("ix_body_weight_records_owner_id", "body_weight_records", ["owner_id"])
    op.create_index("ix_body_weight_records_recorded_on", "body_weight_records", ["recorded_on"])


def downgrade():
    op.drop_table("body_weight_records")
    op.drop_table("exercise_sets")
    op.drop_table("workout_sessions")
