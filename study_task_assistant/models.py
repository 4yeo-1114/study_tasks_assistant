from datetime import date

from sqlalchemy import CheckConstraint, Date, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


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
