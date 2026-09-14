from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Path as FastAPIPath, status

from schemas import TaskCreate, TaskRead
from service import TaskService


def create_app(db_path: str | Path) -> FastAPI:
    app = FastAPI(title="Study Task Assistant")
    service = TaskService(db_path)

    @app.get("/tasks", response_model=list[TaskRead])
    def get_tasks(status: str | None = None):
        return service.list_tasks(status)

    @app.get("/tasks/{task_id}", response_model=TaskRead)
    def get_task(task_id: Annotated[int, FastAPIPath(ge=1)]):
        task = service.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="找不到任务")
        return task

    @app.post(
        "/tasks",
        response_model=TaskRead,
        status_code=status.HTTP_201_CREATED,
    )
    def post_task(task: TaskCreate):
        return service.create_task(task)

    return app


app = create_app(Path(__file__).with_name("tasks.db"))
