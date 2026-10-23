from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from storage.models import Task


def _task_to_dict(task: Task) -> dict:
    result = {
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "due_date": task.due_date.isoformat() if task.due_date else None,
    }
    if task.task_type is not None:
        result.update({
            "task_type": task.task_type,
            "estimated_minutes": task.estimated_minutes,
            "actual_minutes": task.actual_minutes,
        })
    return result


class TaskRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def list_tasks(
        self,
        user_id: int,
        status: str | None = None,
        priority: str | None = None,
    ) -> list[dict]:
        statement = select(Task).where(Task.owner_id == user_id)
        if status is not None:
            statement = statement.where(Task.status == status)
        if priority is not None:
            statement = statement.where(Task.priority == priority)
        statement = statement.order_by(Task.id)

        with self._sessions() as session:
            tasks = session.scalars(statement).all()
            return [_task_to_dict(task) for task in tasks]

    def get_task(self, user_id: int, task_id: int) -> dict | None:
        with self._sessions() as session:
            task = session.scalar(
                select(Task).where(Task.id == task_id, Task.owner_id == user_id)
            )
            return _task_to_dict(task) if task is not None else None

    def progress(self, user_id: int) -> dict:
        with self._sessions() as session:
            tasks = session.scalars(select(Task).where(Task.owner_id == user_id)).all()
            total = len(tasks)
            completed = sum(task.status == "completed" for task in tasks)
            estimated = sum(task.estimated_minutes or 0 for task in tasks)
            actual = sum(task.actual_minutes or 0 for task in tasks)
            return {
                "total": total, "completed": completed, "pending": total - completed,
                "estimated_minutes": estimated, "actual_minutes": actual,
                "completion_rate": completed / total if total else 0.0,
                "time_variance_minutes": actual - estimated,
            }

    def create_task(
        self,
        *,
        user_id: int,
        title: str,
        priority: str,
        due_date: date | None,
        task_type: str | None = None,
        estimated_minutes: int | None = None,
    ) -> dict:
        # with 结束时关闭 Session，底层连接通常归还连接池供后续操作复用。
        with self._sessions.begin() as session:
            task = Task(
                owner_id=user_id,
                title=title,
                status="pending",
                priority=priority,
                due_date=due_date,
                task_type=task_type,
                estimated_minutes=estimated_minutes,
            )
            session.add(task)
            # flush 将 INSERT 发给数据库，以便取得生成的 ID。
            session.flush()
            return _task_to_dict(task)

    def update_task_status(
        self,
        user_id: int,
        task_id: int,
        task_status: str,
        actual_minutes: int | None = None,
    ) -> dict | None:
        with self._sessions.begin() as session:
            task = session.scalar(
                select(Task).where(Task.id == task_id, Task.owner_id == user_id)
            )
            if task is None:
                return None
            task.status = task_status
            if actual_minutes is not None:
                task.actual_minutes = actual_minutes
            session.flush()
            return _task_to_dict(task)

    def delete_task(self, user_id: int, task_id: int) -> bool:
        with self._sessions.begin() as session:
            task = session.scalar(
                select(Task).where(Task.id == task_id, Task.owner_id == user_id)
            )
            if task is None:
                return False
            session.delete(task)
            return True
