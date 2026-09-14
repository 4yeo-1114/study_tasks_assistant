from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Path as FastAPIPath, status

from schemas import TaskCreate, TaskRead
from service import TaskService


def create_app(db_path: str | Path) -> FastAPI:
    app = FastAPI(title="Study Task Assistant")
    service = TaskService(db_path)

    # list[TaskRead] 表示响应是列表，且每个元素都符合 TaskRead。
    @app.get("/tasks", response_model=list[TaskRead])
    def get_tasks(status: str | None = None):
        return service.list_tasks(status)

    # 单条任务响应只需要一个 TaskRead；task_id 必须是大于等于 1 的整数。
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
    # 收到 POST JSON
    # → FastAPI 根据 TaskCreate 创建 Pydantic 模型
    # → 自动校验字段并调用对应校验器
    # → 校验成功才进入 post_task()；失败则返回 422
    def post_task(task: TaskCreate):
        return service.create_task(task)

    return app


app = create_app(Path(__file__).with_name("tasks.db"))
