from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator, model_validator


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


class TaskProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: TaskTitle


class TaskProposalRead(BaseModel):
    id: str
    title: str
    priority: TaskPriority
    due_date: date | None
    expires_at: int
    status: Literal["pending", "confirmed", "rejected"]
    task_id: int | None


class TaskProposalConfirmed(TaskProposalRead):
    task: TaskRead | None


class AgentChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: TaskTitle


class AgentTraceRead(BaseModel):
    step: int
    state: str
    event: str
    tool_call_id: str | None = None
    proposal_id: str | None = None
    tool_name: str | None = None


class AgentChatRead(BaseModel):
    answer: str
    model_steps: int
    tool_calls: int
    total_tokens: int
    trace: list[AgentTraceRead]
    pending_proposals: list[TaskProposalRead]


DocumentSource = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)
]
DocumentVersion = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
]
DocumentContent = Annotated[str, StringConstraints(min_length=1, max_length=1_000_000)]


class DocumentUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: DocumentSource
    content: DocumentContent
    document_version: DocumentVersion = "v1"
    chunk_size: int = 500
    overlap: int = 50

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content 不能为空")
        return value

    @model_validator(mode="after")
    def validate_chunk_window(self):
        if not 100 <= self.chunk_size <= 2_000:
            raise ValueError("chunk_size 必须在 100 到 2000 之间")
        if self.overlap < 0 or self.overlap >= self.chunk_size:
            raise ValueError("overlap 必须大于等于 0 且小于 chunk_size")
        return self


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source: str
    document_version: str
    state: str
    error_message: str | None
    active_version: str | None
    created_at: datetime
    updated_at: datetime


class DocumentIngestRead(DocumentRead):
    chunks_ingested: int
