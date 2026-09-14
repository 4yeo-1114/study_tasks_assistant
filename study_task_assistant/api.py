from pathlib import Path

from fastapi import FastAPI, status

from schemas import TaskCreate, TaskRead
from service import TaskService


def create_app(db_path: str | Path) -> FastAPI:
    app = FastAPI(title="Study Task Assistant")
    service = TaskService(db_path)

    @app.get("/tasks", response_model=list[TaskRead])
    def get_tasks():
        return service.list_tasks()

    @app.post(
        "/tasks",
        response_model=TaskRead,
        status_code=status.HTTP_201_CREATED,
    )
    def post_task(task: TaskCreate):
        return service.create_task(task)

    return app


app = create_app(Path(__file__).with_name("tasks.db"))
