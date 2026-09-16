from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints


TaskTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
TaskPriority = Literal["high", "medium", "low"]
TaskStatus = Literal["pending", "completed"]

# 规定任务创建和读取的字段，即协议。

class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

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


Username = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=3, max_length=32)
]
Password = Annotated[str, StringConstraints(min_length=8, max_length=128)]


class UserCreate(BaseModel):
    username: Username
    password: Password


class UserRead(BaseModel):
    id: int
    username: str


class TokenRead(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
