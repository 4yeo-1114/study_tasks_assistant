import json

import httpx
import pytest

from deepseek_api import DeepSeekAPIError, DeepSeekSettings
from deepseek_tools import (
    LIST_TASKS_TOOL,
    DeepSeekToolResponseError,
    request_tool_proposal,
)
from model_client import ModelMessage
from reliability import RetryPolicy


SETTINGS = DeepSeekSettings(
    api_key="test-key",
    base_url="https://api.deepseek.example",
    model="deepseek-flash",
)
MESSAGES = [
    ModelMessage(role="user", content="查询所有待完成的高优先级任务")
]


def _tool_response(
    *,
    name: str = "list_tasks",
    arguments: str = '{"status":"pending","priority":"high"}',
) -> dict[str, object]:
    return {
        "model": "deepseek-flash",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": arguments,
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {
            "prompt_tokens": 20,
            "completion_tokens": 10,
            "total_tokens": 30,
        },
    }


def test_request_tool_proposal_sends_schema_and_parses_without_execution() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body == {
            "model": "deepseek-flash",
            "messages": [
                {
                    "role": "user",
                    "content": "查询所有待完成的高优先级任务",
                }
            ],
            "tools": [LIST_TASKS_TOOL],
            "tool_choice": "required",
            "thinking": {"type": "disabled"},
            "stream": False,
        }
        return httpx.Response(200, json=_tool_response())

    proposal = request_tool_proposal(
        MESSAGES,
        tools=[LIST_TASKS_TOOL],
        settings=SETTINGS,
        transport=httpx.MockTransport(handler),
    )

    assert proposal.finish_reason == "tool_calls"
    assert proposal.model == "deepseek-flash"
    assert proposal.usage.total_tokens == 30
    assert len(proposal.calls) == 1
    assert proposal.calls[0].call_id == "call_123"
    assert proposal.calls[0].name == "list_tasks"
    assert proposal.calls[0].arguments == {
        "status": "pending",
        "priority": "high",
    }


def test_request_tool_proposal_rejects_invalid_arguments_json() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json=_tool_response(arguments="{not-json}"),
        )
    )

    with pytest.raises(DeepSeekToolResponseError, match="arguments 不是合法 JSON"):
        request_tool_proposal(
            MESSAGES,
            tools=[LIST_TASKS_TOOL],
            settings=SETTINGS,
            transport=transport,
        )


def test_request_tool_proposal_rejects_unknown_tool_name() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json=_tool_response(name="delete_all_tasks", arguments="{}"),
        )
    )

    with pytest.raises(DeepSeekToolResponseError, match="未知工具"):
        request_tool_proposal(
            MESSAGES,
            tools=[LIST_TASKS_TOOL],
            settings=SETTINGS,
            transport=transport,
        )


def test_request_tool_proposal_requires_tool_calls_finish_reason() -> None:
    response = _tool_response()
    response["choices"][0]["finish_reason"] = "stop"
    response["choices"][0]["message"]["tool_calls"] = []
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=response)
    )

    with pytest.raises(DeepSeekToolResponseError, match="没有返回工具提案"):
        request_tool_proposal(
            MESSAGES,
            tools=[LIST_TASKS_TOOL],
            settings=SETTINGS,
            transport=transport,
        )


def test_request_tool_proposal_preserves_retryable_http_error() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            503,
            json={"error": {"message": "temporary failure for test-key"}},
        )
    )

    with pytest.raises(DeepSeekAPIError) as exc_info:
        request_tool_proposal(
            MESSAGES,
            tools=[LIST_TASKS_TOOL],
            settings=SETTINGS,
            transport=transport,
            retry_policy=RetryPolicy(max_attempts=1),
        )

    assert exc_info.value.retryable is True
    assert "test-key" not in str(exc_info.value)


def test_request_tool_proposal_retries_503_then_succeeds() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"error": {"message": "busy"}})
        return httpx.Response(200, json=_tool_response())

    proposal = request_tool_proposal(
        MESSAGES,
        tools=[LIST_TASKS_TOOL],
        settings=SETTINGS,
        transport=httpx.MockTransport(handler),
        retry_policy=RetryPolicy(max_attempts=2),
        sleeper=lambda _: None,
    )

    assert proposal.calls[0].name == "list_tasks"
    assert attempts == 2
