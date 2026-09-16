from repository import TaskRepository
from schemas import TaskCreate, TaskStatus


class TaskService:
    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    def list_tasks(
        self,
        status: str | None = None,
        priority: str | None = None,
    ) -> list[dict]:
        return self._repository.list_tasks(
            status=status,
            priority=priority,
        )

    def get_task(self, task_id: int) -> dict | None:
        return self._repository.get_task(task_id)

    def update_task_status(
        self,
        task_id: int,
        task_status: TaskStatus,
    ) -> dict | None:
        return self._repository.update_task_status(task_id, task_status)

    def delete_task(self, task_id: int) -> bool:
        return self._repository.delete_task(task_id)

    def create_task(self, task: TaskCreate) -> dict:
        return self._repository.create_task(
            title=task.title,
            priority=task.priority,
            due_date=task.due_date,
        )
