from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


TaskTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
TaskPriority = Literal["high", "medium", "low"]
TaskStatus = Literal["pending", "completed"]
TaskType = Literal["learning", "fitness"]

# 规定任务创建和读取的字段，即协议。

class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: TaskTitle
    priority: TaskPriority = "medium"
    due_date: date | None = None
    task_type: TaskType | None = None
    estimated_minutes: int | None = None

    @field_validator("estimated_minutes")
    @classmethod
    def validate_estimated_minutes(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("estimated_minutes 必须大于 0")
        return value


class TaskStatusUpdate(BaseModel):
    status: TaskStatus
    actual_minutes: int | None = None

    @field_validator("actual_minutes")
    @classmethod
    def validate_actual_minutes(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("actual_minutes 必须大于 0")
        return value


class TaskRead(BaseModel):
    id: int
    title: str
    status: str
    priority: str
    due_date: date | None
    task_type: TaskType | None = None
    estimated_minutes: int | None = None
    actual_minutes: int | None = None


class TaskProgressRead(BaseModel):
    total: int
    completed: int
    pending: int
    estimated_minutes: int
    actual_minutes: int
    completion_rate: float
    time_variance_minutes: int


class ExerciseSetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exercise_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    weight_kg: float
    reps: int

    @field_validator("weight_kg", "reps")
    @classmethod
    def positive_values(cls, value):
        if value <= 0:
            raise ValueError("训练重量和次数必须大于 0")
        return value


class WorkoutCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workout_date: date
    notes: str | None = None
    sets: list[ExerciseSetCreate]

    @field_validator("sets")
    @classmethod
    def require_sets(cls, value):
        if not value:
            raise ValueError("至少需要一组训练记录")
        return value


class WorkoutRead(BaseModel):
    id: int
    workout_date: date
    notes: str | None
    sets: list[ExerciseSetCreate]
    volume: float


class BodyWeightCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recorded_on: date
    weight_kg: float

    @field_validator("weight_kg")
    @classmethod
    def positive_weight(cls, value):
        if value <= 0:
            raise ValueError("体重必须大于 0")
        return value


class BodyWeightRead(BodyWeightCreate):
    id: int


class FitnessProgressRead(BaseModel):
    volume_by_exercise: dict[str, float]
    exercise_pr: dict[str, float]
    weekly_weight: dict[str, float]


class FitnessCsvRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    csv_text: str = Field(min_length=1, max_length=2_000_000)


class FitnessCsvPreviewRead(BaseModel):
    row_count: int
    workout_count: int
    weight_count: int
    rows: list[dict]


class FitnessCsvCommitRead(BaseModel):
    row_count: int
    workout_count: int
    weight_count: int


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


class UserProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    learning_goal: str | None = Field(default=None, max_length=500)
    training_days_per_week: int | None = None
    preferences: str | None = Field(default=None, max_length=2_000)
    limitations: str | None = Field(default=None, max_length=2_000)
    daily_minutes: int | None = None

    @field_validator("learning_goal", "preferences", "limitations")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("文本字段不能只包含空白字符")
        return value

    @field_validator("training_days_per_week")
    @classmethod
    def validate_training_days(cls, value: int | None) -> int | None:
        if value is not None and not 0 <= value <= 7:
            raise ValueError("training_days_per_week 必须在 0 到 7 之间")
        return value

    @field_validator("daily_minutes")
    @classmethod
    def validate_daily_minutes(cls, value: int | None) -> int | None:
        if value is not None and not 1 <= value <= 1_440:
            raise ValueError("daily_minutes 必须在 1 到 1440 之间")
        return value


class UserProfileRead(UserProfileUpdate):
    revision: int
    plan_version: int


class WeeklyPlanTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: TaskTitle
    task_type: TaskType
    due_date: date
    estimated_minutes: int = Field(ge=1, le=1440)


class WeeklyPlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    week_start: date
    expected_profile_revision: int = Field(ge=1)
    base_plan_version: int = Field(ge=0)
    idempotency_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    tasks: list[WeeklyPlanTask] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_week(self):
        if self.week_start.weekday() != 0:
            raise ValueError("week_start 必须是周一")
        week_end = self.week_start + timedelta(days=6)
        if any(task.due_date < self.week_start or task.due_date > week_end for task in self.tasks):
            raise ValueError("任务日期必须位于该周的周一至周日")
        return self


class WeeklyPlanAdjustmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]


class WeeklyPlanTaskRead(BaseModel):
    id: int | None = None
    title: str
    status: TaskStatus = "pending"
    priority: TaskPriority = "medium"
    due_date: date
    task_type: TaskType
    estimated_minutes: int
    actual_minutes: int | None = None


class WeeklyPlanRead(BaseModel):
    id: str
    week_start: date
    expected_profile_revision: int
    base_plan_version: int
    status: Literal["pending", "confirmed", "rejected"]
    plan_version: int | None
    tasks: list[WeeklyPlanTaskRead]
    plan_kind: Literal["weekly", "adjustment"] = "weekly"
    source_plan_id: str | None = None
    adjustment_summary: str | None = None
    created_at: datetime


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
    idempotency_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)] | None = None

    message: TaskTitle
    session_id: Annotated[str, StringConstraints(min_length=1, max_length=32)] | None = None


class AgentTraceRead(BaseModel):
    step: int
    state: str
    event: str
    tool_call_id: str | None = None
    proposal_id: str | None = None
    tool_name: str | None = None


class AgentChatRead(BaseModel):
    session_id: str
    run_id: str
    answer: str
    model_steps: int
    tool_calls: int
    total_tokens: int
    trace: list[AgentTraceRead]
    pending_proposals: list[TaskProposalRead]
    pending_plans: list[WeeklyPlanRead] = Field(default_factory=list)


class AgentMessageRead(BaseModel):
    sequence: int
    role: Literal["user", "assistant"]
    content: str


class AgentRunRead(BaseModel):
    id: str
    status: Literal["running", "succeeded", "failed"]
    error_type: str | None


class AgentSessionRead(BaseModel):
    id: str
    status: Literal["active", "closed"]
    messages: list[AgentMessageRead]
    runs: list[AgentRunRead]


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


class WeeklyPlanWorkflowRead(BaseModel):
    plan_id: str
    status: Literal["pending", "confirmed", "rejected"]
    waiting_for_confirmation: bool
