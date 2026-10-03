import pytest

from model_client import (
    FakeModelClient,
    ModelMessage,
    ModelTimeoutError,
    TextResponse,
    ToolCall,
)


def test_fake_model_returns_fixed_text_and_records_input():
    output = TextResponse(text="我可以帮你查询任务。")
    client = FakeModelClient(output)
    messages = [ModelMessage(role="user", content="我有哪些任务？")]

    assert client.complete(messages, timeout_seconds=2) == output
    assert client.calls == [messages]


def test_fake_model_can_propose_a_tool_call_without_executing_it():
    output = ToolCall(
        name="create_task",
        arguments={"title": "复习 SQL", "user_id": 999},
    )
    client = FakeModelClient(output)

    result = client.complete(
        [ModelMessage(role="user", content="帮我创建复习 SQL 的任务")],
        timeout_seconds=2,
    )

    assert result == output
    assert result.arguments["user_id"] == 999


def test_fake_model_raises_timeout_before_returning_output():
    client = FakeModelClient(
        TextResponse(text="不会返回"),
        required_latency_seconds=3,
    )

    with pytest.raises(ModelTimeoutError, match="3 秒.*1 秒"):
        client.complete(
            [ModelMessage(role="user", content="查询任务")],
            timeout_seconds=1,
        )


def test_timeout_must_be_positive():
    client = FakeModelClient(TextResponse(text="不会返回"))

    with pytest.raises(ValueError, match="必须大于 0"):
        client.complete(
            [ModelMessage(role="user", content="查询任务")],
            timeout_seconds=0,
        )
