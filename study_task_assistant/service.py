from pathlib import Path

import repository
from schemas import TaskCreate


class TaskService:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = db_path

    def initialize(self) -> None:
        repository.init_db(self._db_path)

    def list_tasks(self, status: str | None = None) -> list[dict]:
        self.initialize()
        return repository.list_tasks(self._db_path, status)

    def get_task(self, task_id: int) -> dict | None:
        self.initialize()
        return repository.get_task(self._db_path, task_id)

    def create_task(self, task: TaskCreate) -> dict:
        self.initialize()
        return repository.create_task(
            self._db_path,
            title=task.title,
            priority=task.priority,
            due_date=task.due_date,
        )
