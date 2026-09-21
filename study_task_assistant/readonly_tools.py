from dataclasses import dataclass
from typing import Annotated, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from deepseek_tools import LIST_TASKS_TOOL, ToolCallProposal
from schemas import TaskPriority, TaskStatus


GET_TASK_TOOL: dict[str, object] = {
    "type": "function",
    "function": {
        "name": "get_task",
        "description": "按任务 ID 查询当前用户的一条学习任务；只读，不修改任务。",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "任务 ID",
                }
            },
            "required": ["task_id"],
            "additionalProperties": False,
        },
    },
}

READ_ONLY_TOOLS = [LIST_TASKS_TOOL, GET_TASK_TOOL]


class ToolNotAllowedError(ValueError):
    pass


class ToolArgumentsError(ValueError):
    pass


class ListTasksArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TaskStatus | None = None
    priority: TaskPriority | None = None


class GetTaskArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: Annotated[int, Field(strict=True, ge=1)]


class TaskQueryService(Protocol):
    def list_tasks(
        self,
        user_id: int,
        status: str | None = None,
        priority: str | None = None,
    ) -> list[dict]: ...

    def get_task(self, user_id: int, task_id: int) -> dict | None: ...


@dataclass(frozen=True)
class ToolExecutionResult:
    call_id: str
    name: str
    output: list[dict] | dict | None


def execute_readonly_tool(
    call: ToolCallProposal,
    *,
    user_id: int,
    service: TaskQueryService,
) -> ToolExecutionResult:
    if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id < 1:
        raise ValueError("可信 user_id 必须是正整数")

    if call.name == "list_tasks":
        arguments = _validate_arguments(ListTasksArguments, call)
        output = service.list_tasks(
            user_id,
            status=arguments.status,
            priority=arguments.priority,
        )
    elif call.name == "get_task":
        arguments = _validate_arguments(GetTaskArguments, call)
        output = service.get_task(user_id, arguments.task_id)
    else:
        raise ToolNotAllowedError(
            f"工具 {call.name} 不在只读白名单中"
        )

    return ToolExecutionResult(
        call_id=call.call_id,
        name=call.name,
        output=output,
    )


def _validate_arguments(
    model: type[ListTasksArguments] | type[GetTaskArguments],
    call: ToolCallProposal,
) -> ListTasksArguments | GetTaskArguments:
    try:
        return model.model_validate(call.arguments)
    except ValidationError as exc:
        raise ToolArgumentsError(
            f"工具 {call.name} 参数校验失败"
        ) from exc
