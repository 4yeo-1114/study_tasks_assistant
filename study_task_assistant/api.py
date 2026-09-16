import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Path as FastAPIPath, Response, status

from database import Database
from repository import TaskRepository
from schemas import TaskCreate, TaskPriority, TaskRead, TaskStatusUpdate
from service import TaskService


def normalize_database_url(value: str | Path) -> str:
    if isinstance(value, Path):
        return f"sqlite+pysqlite:///{value.resolve().as_posix()}"
    if "://" in value:
        return value
    return f"sqlite+pysqlite:///{Path(value).resolve().as_posix()}"


def get_default_database_url() -> str:
    default_path = Path(__file__).with_name("tasks.db").resolve().as_posix()
    return os.environ.get(
        "DATABASE_URL",
        f"sqlite+pysqlite:///{default_path}",
    )


def create_app(database_location: str | Path) -> FastAPI:
    database = Database(normalize_database_url(database_location))
    service = TaskService(TaskRepository(database.sessions))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            database.dispose()

    app = FastAPI(title="Study Task Assistant", lifespan=lifespan)
    app.state.database = database

    @app.get("/tasks", response_model=list[TaskRead])
    def get_tasks(
        status: str | None = None,
        priority: TaskPriority | None = None,
    ):
        return service.list_tasks(status=status, priority=priority)

    @app.get("/tasks/{task_id}", response_model=TaskRead)
    def get_task(task_id: Annotated[int, FastAPIPath(ge=1)]):
        task = service.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="找不到任务")
        return task

    @app.patch("/tasks/{task_id}", response_model=TaskRead)
    def update_task_status(
        task_id: Annotated[int, FastAPIPath(ge=1)],
        update: TaskStatusUpdate,
    ):
        task = service.update_task_status(task_id, update.status)
        if task is None:
            raise HTTPException(status_code=404, detail="找不到任务")
        return task

    @app.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_task(
        task_id: Annotated[int, FastAPIPath(ge=1)],
    ) -> Response:
        if not service.delete_task(task_id):
            raise HTTPException(status_code=404, detail="找不到任务")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post(
        "/tasks",
        response_model=TaskRead,
        status_code=status.HTTP_201_CREATED,
    )
    def post_task(task: TaskCreate):
        return service.create_task(task)

    return app


app = create_app(get_default_database_url())
