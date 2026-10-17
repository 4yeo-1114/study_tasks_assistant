from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from storage.models import Task


def _task_to_dict(task: Task) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "due_date": task.due_date.isoformat() if task.due_date else None,
    }


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

    def create_task(
        self,
        *,
        user_id: int,
        title: str,
        priority: str,
        due_date: date | None,
    ) -> dict:
        # with 结束时关闭 Session，底层连接通常归还连接池供后续操作复用。
        with self._sessions.begin() as session:
            task = Task(
                owner_id=user_id,
                title=title,
                status="pending",
                priority=priority,
                due_date=due_date,
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
    ) -> dict | None:
        with self._sessions.begin() as session:
            task = session.scalar(
                select(Task).where(Task.id == task_id, Task.owner_id == user_id)
            )
            if task is None:
                return None
            task.status = task_status
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
