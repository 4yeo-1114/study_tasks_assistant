import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Path as FastAPIPath, Response, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

from auth import AuthService
from database import Database
from repository import TaskRepository
from schemas import (
    TaskCreate,
    TaskPriority,
    TaskRead,
    TaskStatusUpdate,
    TokenRead,
    UserCreate,
    UserRead,
)
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


def create_app(database_location: str | Path, *, token_secret: str | None = None) -> FastAPI:
    database = Database(normalize_database_url(database_location))
    service = TaskService(TaskRepository(database.sessions))
    secret = token_secret or os.environ.get("STUDY_TASK_SECRET_KEY") or secrets.token_hex(32)
    if len(secret.encode("utf-8")) < 32:
        database.dispose()
        raise ValueError("STUDY_TASK_SECRET_KEY 至少需要 32 字节")
    auth = AuthService(database.sessions, secret)
    oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

    def current_user_id(token: Annotated[str, Depends(oauth2_scheme)]) -> int:
        user_id = auth.user_id_for_token(token)
        if user_id is None:
            raise HTTPException(status_code=401, detail="无效或过期的登录凭据")
        return user_id

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            database.dispose()

    app = FastAPI(title="Study Task Assistant", lifespan=lifespan)
    app.state.database = database

    @app.post("/auth/register", response_model=UserRead, status_code=201)
    def register(user: UserCreate):
        created = auth.register(user.username, user.password)
        if created is None:
            raise HTTPException(status_code=409, detail="用户名已存在")
        return created

    @app.post("/auth/login", response_model=TokenRead)
    def login(form: Annotated[OAuth2PasswordRequestForm, Depends()]):
        token = auth.login(form.username.strip().lower(), form.password)
        if token is None:
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        return {"access_token": token, "token_type": "bearer"}

    @app.get("/tasks", response_model=list[TaskRead])
    def get_tasks(
        user_id: Annotated[int, Depends(current_user_id)],
        status: str | None = None,
        priority: TaskPriority | None = None,
    ):
        return service.list_tasks(user_id, status=status, priority=priority)

    @app.get("/tasks/{task_id}", response_model=TaskRead)
    def get_task(
        task_id: Annotated[int, FastAPIPath(ge=1)],
        user_id: Annotated[int, Depends(current_user_id)],
    ):
        task = service.get_task(user_id, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="找不到任务")
        return task

    @app.patch("/tasks/{task_id}", response_model=TaskRead)
    def update_task_status(
        task_id: Annotated[int, FastAPIPath(ge=1)],
        update: TaskStatusUpdate,
        user_id: Annotated[int, Depends(current_user_id)],
    ):
        task = service.update_task_status(user_id, task_id, update.status)
        if task is None:
            raise HTTPException(status_code=404, detail="找不到任务")
        return task

    @app.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_task(
        task_id: Annotated[int, FastAPIPath(ge=1)],
        user_id: Annotated[int, Depends(current_user_id)],
    ) -> Response:
        if not service.delete_task(user_id, task_id):
            raise HTTPException(status_code=404, detail="找不到任务")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post(
        "/tasks",
        response_model=TaskRead,
        status_code=status.HTTP_201_CREATED,
    )
    def post_task(task: TaskCreate, user_id: Annotated[int, Depends(current_user_id)]):
        return service.create_task(user_id, task)

    return app


app = create_app(get_default_database_url())
