from datetime import date, datetime

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("username", name="uq_users_username"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)


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
