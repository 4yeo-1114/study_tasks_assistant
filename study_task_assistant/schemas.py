from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints, field_validator


TaskTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
TaskPriority = Literal["high", "medium", "low"]


class TaskCreate(BaseModel):
    title: TaskTitle
    priority: TaskPriority = "medium"
    due_date: str | None = None

    @field_validator("due_date")
    @classmethod
    def validate_due_date(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise ValueError("due_date 必须是实际存在的 YYYY-MM-DD 日期") from None
        return value


class TaskRead(BaseModel):
    id: int
    title: str
    status: str
    priority: str
    due_date: str | None
