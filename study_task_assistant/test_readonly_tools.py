import pytest

from deepseek_tools import ToolCallProposal
from readonly_tools import (
    ToolArgumentsError,
    ToolNotAllowedError,
    execute_readonly_tool,
)


class FakeTaskQueryService:
    def __init__(self) -> None:
        self.list_calls: list[tuple[int, str | None, str | None]] = []
        self.get_calls: list[tuple[int, int]] = []
        self.tasks_by_user = {
            1: [{"id": 1, "title": "用户一任务", "priority": "high"}],
            2: [{"id": 2, "title": "用户二任务", "priority": "low"}],
        }

    def list_tasks(
        self,
        user_id: int,
        status: str | None = None,
        priority: str | None = None,
    ) -> list[dict]:
        self.list_calls.append((user_id, status, priority))
        return self.tasks_by_user.get(user_id, [])

    def get_task(self, user_id: int, task_id: int) -> dict | None:
        self.get_calls.append((user_id, task_id))
        return next(
            (
                task
                for task in self.tasks_by_user.get(user_id, [])
                if task["id"] == task_id
            ),
            None,
        )


def test_list_tasks_uses_trusted_user_and_validated_filters() -> None:
    service = FakeTaskQueryService()
    call = ToolCallProposal(
        call_id="call-list",
        name="list_tasks",
        arguments={"status": "pending", "priority": "high"},
    )

    result = execute_readonly_tool(call, user_id=1, service=service)

    assert service.list_calls == [(1, "pending", "high")]
    assert result.call_id == "call-list"
    assert result.name == "list_tasks"
    assert result.output == service.tasks_by_user[1]


def test_get_task_cannot_read_another_users_task() -> None:
    service = FakeTaskQueryService()
    call = ToolCallProposal(
        call_id="call-get",
        name="get_task",
        arguments={"task_id": 1},
    )

    result = execute_readonly_tool(call, user_id=2, service=service)

    assert service.get_calls == [(2, 1)]
    assert result.output is None


@pytest.mark.parametrize("identity_field", ["user_id", "owner_id"])
def test_model_cannot_supply_identity(identity_field: str) -> None:
    service = FakeTaskQueryService()
    call = ToolCallProposal(
        call_id="call-forged-user",
        name="list_tasks",
        arguments={identity_field: 999},
    )

    with pytest.raises(ToolArgumentsError, match="参数校验失败"):
        execute_readonly_tool(call, user_id=1, service=service)

    assert service.list_calls == []


def test_invalid_priority_is_rejected_before_service_call() -> None:
    service = FakeTaskQueryService()
    call = ToolCallProposal(
        call_id="call-invalid",
        name="list_tasks",
        arguments={"priority": "urgent"},
    )

    with pytest.raises(ToolArgumentsError, match="参数校验失败"):
        execute_readonly_tool(call, user_id=1, service=service)

    assert service.list_calls == []


def test_unknown_tool_is_not_called() -> None:
    service = FakeTaskQueryService()
    call = ToolCallProposal(
        call_id="call-delete",
        name="delete_task",
        arguments={"task_id": 1},
    )

    with pytest.raises(ToolNotAllowedError, match="不在只读白名单"):
        execute_readonly_tool(call, user_id=1, service=service)

    assert service.list_calls == []
    assert service.get_calls == []


def test_list_tasks_supports_status_only_filter() -> None:
    service = FakeTaskQueryService()
    call = ToolCallProposal(
        call_id="call-completed",
        name="list_tasks",
        arguments={"status": "completed"},
    )

    result = execute_readonly_tool(
        call,
        user_id=1,
        service=service,
    )

    assert service.list_calls == [(1, "completed", None)]
    assert result.call_id == "call-completed"
    assert result.name == "list_tasks"
    assert result.output == service.tasks_by_user[1]
