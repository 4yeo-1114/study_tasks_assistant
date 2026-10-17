import json

import httpx
import pytest

from agent.agent_loop import (
    AgentBudget,
    AgentBudgetExceededError,
    run_readonly_agent,
)
from llm.deepseek_api import DeepSeekSettings


SETTINGS = DeepSeekSettings("key", "https://api.deepseek.example", "model")


class Service:
    def __init__(self):
        self.calls = []

    def list_tasks(self, user_id, status=None, priority=None):
        self.calls.append((user_id, status, priority))
        return []


def tool_response(*, count=1, tokens=10):
    calls = [
        {
            "id": f"call-{index}",
            "type": "function",
            "function": {"name": "list_tasks", "arguments": "{}"},
        }
        for index in range(count)
    ]
    return {
        "usage": {"total_tokens": tokens},
        "choices": [{"finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": None, "tool_calls": calls,
        }}],
    }


def final_response(*, tokens=10):
    return {
        "usage": {"total_tokens": tokens},
        "choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": "完成",
        }}],
    }


def test_tool_budget_preflights_whole_batch_before_any_execution():
    service = Service()
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=tool_response(count=2))
    )

    with pytest.raises(AgentBudgetExceededError, match="工具"):
        run_readonly_agent(
            "查任务",
            user_id=1,
            service=service,
            settings=SETTINGS,
            budget=AgentBudget(max_tool_calls=1, max_total_tokens=100),
            transport=transport,
        )

    assert service.calls == []


def test_agent_accumulates_provider_token_usage():
    responses = iter([tool_response(tokens=20), final_response(tokens=30)])
    result = run_readonly_agent(
        "查任务",
        user_id=1,
        service=Service(),
        settings=SETTINGS,
        budget=AgentBudget(max_tool_calls=2, max_total_tokens=100),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=next(responses))
        ),
    )
    assert result.total_tokens == 50


def test_token_budget_stops_before_tool_execution():
    service = Service()
    with pytest.raises(AgentBudgetExceededError, match="Token"):
        run_readonly_agent(
            "查任务",
            user_id=1,
            service=service,
            settings=SETTINGS,
            budget=AgentBudget(max_tool_calls=2, max_total_tokens=10),
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json=tool_response(tokens=11)
                )
            ),
        )
    assert service.calls == []
