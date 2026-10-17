from tasks.repository import TaskRepository
from web.schemas import TaskCreate, TaskStatus


class TaskService:
    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    def list_tasks(
        self,
        user_id: int,
        status: str | None = None,
        priority: str | None = None,
    ) -> list[dict]:
        return self._repository.list_tasks(
            user_id,
            status=status,
            priority=priority,
        )

    def get_task(self, user_id: int, task_id: int) -> dict | None:
        return self._repository.get_task(user_id, task_id)

    def update_task_status(
        self,
        user_id: int,
        task_id: int,
        task_status: TaskStatus,
    ) -> dict | None:
        return self._repository.update_task_status(user_id, task_id, task_status)

    def delete_task(self, user_id: int, task_id: int) -> bool:
        return self._repository.delete_task(user_id, task_id)

    def create_task(self, user_id: int, task: TaskCreate) -> dict:
        return self._repository.create_task(
            user_id=user_id,
            title=task.title,
            priority=task.priority,
            due_date=task.due_date,
        )
