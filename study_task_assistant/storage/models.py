from datetime import date, datetime

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, Float, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("username", name="uq_users_username"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)


class UserProfile(Base):
    __tablename__ = "user_profiles"
    __table_args__ = (
        CheckConstraint(
            "training_days_per_week IS NULL OR training_days_per_week BETWEEN 0 AND 7",
            name="user_profiles_training_days_range",
        ),
        CheckConstraint(
            "daily_minutes IS NULL OR daily_minutes BETWEEN 1 AND 1440",
            name="user_profiles_daily_minutes_range",
        ),
        UniqueConstraint("owner_id", name="uq_user_profiles_owner_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    learning_goal: Mapped[str | None] = mapped_column(String(500), nullable=True)
    training_days_per_week: Mapped[int | None] = mapped_column(nullable=True)
    preferences: Mapped[str | None] = mapped_column(String(2_000), nullable=True)
    limitations: Mapped[str | None] = mapped_column(String(2_000), nullable=True)
    daily_minutes: Mapped[int | None] = mapped_column(nullable=True)
    revision: Mapped[int] = mapped_column(nullable=False, default=1)
    plan_version: Mapped[int] = mapped_column(nullable=False, default=0)


class WeeklyPlan(Base):
    __tablename__ = "weekly_plans"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'confirmed', 'rejected')", name="weekly_plans_status_check"),
        UniqueConstraint("owner_id", "idempotency_key", name="uq_weekly_plans_owner_idempotency_key"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    week_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    expected_profile_revision: Mapped[int] = mapped_column(nullable=False)
    base_plan_version: Mapped[int] = mapped_column(nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    task_snapshot: Mapped[list] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    plan_version: Mapped[int | None] = mapped_column(nullable=True)
    task_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    plan_kind: Mapped[str] = mapped_column(String, nullable=False, default="weekly")
    source_plan_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    adjustment_summary: Mapped[str | None] = mapped_column(String(2_000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AgentSession(Base):
    __tablename__ = "agent_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'closed')", name="agent_sessions_status_check"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    message_sequence: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="agent_runs_status_check",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("agent_sessions.id"), nullable=False, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="agent_messages_role_check"),
        UniqueConstraint("session_id", "sequence", name="uq_agent_messages_session_sequence"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("agent_sessions.id"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'completed')",
            name="tasks_status_check",
        ),
        CheckConstraint(
            "priority IN ('high', 'medium', 'low')",
            name="tasks_priority_check",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", name="fk_tasks_owner_id_users"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="pending",
    )
    priority: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="medium",
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    task_type: Mapped[str | None] = mapped_column(String, nullable=True)
    estimated_minutes: Mapped[int | None] = mapped_column(nullable=True)
    actual_minutes: Mapped[int | None] = mapped_column(nullable=True)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'processing', 'ready', 'failed', 'deleting', 'deleted')",
            name="documents_state_check",
        ),
        UniqueConstraint(
            "owner_id", "source", "document_version",
            name="uq_documents_owner_source_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    document_version: Mapped[str] = mapped_column(String, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    active_version: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class TaskProposal(Base):
    __tablename__ = "task_proposals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'rejected')",
            name="task_proposals_status_check",
        ),
        UniqueConstraint(
            "owner_id", "idempotency_key",
            name="uq_task_proposals_owner_idempotency_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    priority: Mapped[str] = mapped_column(String, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expires_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    # Historical ID remains useful after the task is deleted; it is not a live FK.
    task_id: Mapped[int | None] = mapped_column(nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)


class WorkoutSession(Base):
    __tablename__ = "workout_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    workout_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)


class ExerciseSet(Base):
    __tablename__ = "exercise_sets"
    __table_args__ = (
        CheckConstraint("weight_kg > 0", name="exercise_sets_weight_check"),
        CheckConstraint("reps > 0", name="exercise_sets_reps_check"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("workout_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    exercise_name: Mapped[str] = mapped_column(String, nullable=False)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    reps: Mapped[int] = mapped_column(nullable=False)


class BodyWeightRecord(Base):
    __tablename__ = "body_weight_records"
    __table_args__ = (
        UniqueConstraint("owner_id", "recorded_on", name="uq_body_weight_owner_date"),
        CheckConstraint("weight_kg > 0", name="body_weight_positive_check"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    recorded_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)


class FitnessImport(Base):
    __tablename__ = "fitness_imports"
    __table_args__ = (UniqueConstraint("owner_id", "import_key", name="uq_fitness_import_owner_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    import_key: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(nullable=False)
    workout_count: Mapped[int] = mapped_column(nullable=False)
    weight_count: Mapped[int] = mapped_column(nullable=False)
