from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints


TaskTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
TaskPriority = Literal["high", "medium", "low"]
TaskStatus = Literal["pending", "completed"]

# 规定任务创建和读取的字段，即协议。

class TaskCreate(BaseModel):
    title: TaskTitle
    priority: TaskPriority = "medium"
    due_date: date | None = None


class TaskStatusUpdate(BaseModel):
    status: TaskStatus


class TaskRead(BaseModel):
    id: int
    title: str
    status: str
    priority: str
    due_date: date | None
