import json
import logging

import httpx
import pytest

from agent.agent_loop import AgentStepLimitError, run_readonly_agent
from web.auth import AuthService
from storage.database import Database
from llm.deepseek_api import DeepSeekAPIError, DeepSeekSettings, DeepSeekTimeoutError
from llm.deepseek_tools import DeepSeekToolResponseError
from agent.readonly_tools import ToolArgumentsError
from core.reliability import RetryPolicy
from storage.migration import upgrade_database
from tasks.repository import TaskRepository
from web.schemas import TaskCreate
from tasks.service import TaskService
from core.observability import request_context


SETTINGS = DeepSeekSettings("test-key", "https://api.deepseek.example", "deepseek-flash")


class FakeService:
    def __init__(self):
        self.calls = []

    def list_tasks(self, user_id, status=None, priority=None):
        self.calls.append((user_id, status, priority))
        return [{"id": 7, "title": "复习 SQL", "status": "pending", "priority": "high"}]

    def get_task(self, user_id, task_id):
        self.calls.append((user_id, task_id))
        return None


def tool_response(call_id="call-1", arguments='{"status":"pending"}', name="list_tasks"):
    return {"choices": [{"finish_reason": "tool_calls", "message": {
        "role": "assistant", "content": None, "tool_calls": [{"id": call_id,
        "type": "function", "function": {"name": name, "arguments": arguments}}]}}]}


def final_response(text="你有一条待完成任务。"):
    return {"choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": text}}]}


def test_loop_sends_assistant_call_and_matching_tool_result():
    requests = []
    service = FakeService()

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body["tool_choice"] == ("required" if len(requests) == 1 else "auto")
        assert body["thinking"] == {"type": "disabled"}
        if len(requests) == 1:
            assert body["messages"] == [{"role": "user", "content": "查待完成任务"}]
            return httpx.Response(200, json=tool_response())
        assert body["messages"][1]["role"] == "assistant"
        assert body["messages"][1]["tool_calls"][0]["id"] == "call-1"
        assert body["messages"][2]["role"] == "tool"
        assert body["messages"][2]["tool_call_id"] == "call-1"
        assert json.loads(body["messages"][2]["content"])[0]["id"] == 7
        return httpx.Response(200, json=final_response())

    result = run_readonly_agent("查待完成任务", user_id=3, service=service,
                                settings=SETTINGS, transport=httpx.MockTransport(handler))
    assert result.answer == "你有一条待完成任务。"
    assert result.model_steps == 2
    assert result.tool_calls == 1
    assert service.calls == [(3, "pending", None)]


def test_loop_handles_two_model_tool_rounds():
    service = FakeService()
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        if count == 1:
            return httpx.Response(200, json=tool_response("call-a"))
        if count == 2:
            return httpx.Response(200, json=tool_response("call-b", '{"priority":"high"}'))
        return httpx.Response(200, json=final_response("完成"))

    result = run_readonly_agent("查任务", user_id=1, service=service,
                                settings=SETTINGS, max_model_steps=3,
                                transport=httpx.MockTransport(handler))
    assert (result.model_steps, result.tool_calls, result.answer) == (3, 2, "完成")


def test_loop_logs_correlated_model_durations_without_prompt_or_key(caplog):
    service = FakeService()
    requests = 0
    private_question = "private question text"

    def handler(request):
        nonlocal requests
        requests += 1
        if requests == 1:
            return httpx.Response(200, json=tool_response("call-observed"))
        return httpx.Response(200, json=final_response("完成"))

    with request_context("http-observed"):
        with caplog.at_level(logging.INFO, logger="study_task.agent"):
            run_readonly_agent(
                private_question,
                user_id=1,
                service=service,
                settings=SETTINGS,
                transport=httpx.MockTransport(handler),
            )

    events = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "study_task.agent" and record.getMessage().startswith("{")
    ]
    model_events = [
        event for event in events if event["event"] == "model_request_completed"
    ]
    assert [event["step"] for event in model_events] == [1, 2]
    assert len({event["agent_run_id"] for event in model_events}) == 1
    assert all(event["request_id"] == "http-observed" for event in model_events)
    assert all(event["duration_ms"] >= 0 for event in model_events)
    assert private_question not in caplog.text
    assert SETTINGS.api_key not in caplog.text


def test_loop_stops_before_executing_tool_at_step_limit():
    service = FakeService()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=tool_response()))
    with pytest.raises(AgentStepLimitError, match="步数上限"):
        run_readonly_agent("查任务", user_id=1, service=service,
                           settings=SETTINGS, max_model_steps=1, transport=transport)
    assert service.calls == []


def test_loop_step_limit_after_one_completed_tool_round():
    service = FakeService()
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(200, json=tool_response("call-first"))
        assert body["messages"][1]["tool_calls"][0]["id"] == "call-first"
        assert body["messages"][2]["tool_call_id"] == "call-first"
        return httpx.Response(200, json=tool_response("call-second"))

    with pytest.raises(AgentStepLimitError, match="步数上限"):
        run_readonly_agent("查任务", user_id=1, service=service,
                           settings=SETTINGS, max_model_steps=2,
                           transport=httpx.MockTransport(handler))
    assert len(requests) == 2
    assert service.calls == [(1, "pending", None)]


@pytest.mark.parametrize("response,error", [
    (tool_response(name="delete_task"), DeepSeekToolResponseError),
    (tool_response(arguments='{"user_id":999}'), ToolArgumentsError),
])
def test_loop_stops_on_invalid_tool(response, error):
    service = FakeService()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=response))
    with pytest.raises(error):
        run_readonly_agent("查任务", user_id=1, service=service,
                           settings=SETTINGS, transport=transport)
    assert service.calls == []


def test_loop_rejects_non_final_stop_and_propagates_upstream_error():
    service = FakeService()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        "choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": "半句"}}]}))
    with pytest.raises(DeepSeekToolResponseError, match="未完整结束"):
        run_readonly_agent("查任务", user_id=1, service=service,
                           settings=SETTINGS, transport=transport)
    assert service.calls == []


def test_loop_rejects_reused_call_id_across_rounds():
    service = FakeService()
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=tool_response("same-id"))
    )
    with pytest.raises(DeepSeekToolResponseError, match="Call ID 重复"):
        run_readonly_agent("查任务", user_id=1, service=service,
                           settings=SETTINGS, max_model_steps=3, transport=transport)
    assert len(service.calls) == 1


def test_loop_maps_upstream_http_and_timeout():
    service = FakeService()
    http_error = httpx.MockTransport(lambda request: httpx.Response(
        503, json={"error": {"message": "temporary failure for test-key"}}))
    with pytest.raises(DeepSeekAPIError) as exc_info:
        run_readonly_agent("查任务", user_id=1, service=service,
                           settings=SETTINGS, transport=http_error,
                           retry_policy=RetryPolicy(max_attempts=1))
    assert exc_info.value.retryable is True
    assert "test-key" not in str(exc_info.value)

    def timeout(request):
        raise httpx.ReadTimeout("stalled", request=request)

    with pytest.raises(DeepSeekTimeoutError):
        run_readonly_agent("查任务", user_id=1, service=service,
                           settings=SETTINGS, transport=httpx.MockTransport(timeout),
                           retry_policy=RetryPolicy(max_attempts=1))
    assert service.calls == []


def test_loop_retries_only_model_http_request_and_executes_tool_once():
    service = FakeService()
    http_attempts = 0

    def handler(request):
        nonlocal http_attempts
        http_attempts += 1
        if http_attempts == 1:
            return httpx.Response(503, json={"error": {"message": "busy"}})
        if http_attempts == 2:
            return httpx.Response(200, json=tool_response("call-retried"))
        return httpx.Response(200, json=final_response("完成"))

    result = run_readonly_agent(
        "查任务",
        user_id=1,
        service=service,
        settings=SETTINGS,
        transport=httpx.MockTransport(handler),
        retry_policy=RetryPolicy(max_attempts=3),
        sleeper=lambda _: None,
    )

    assert result.answer == "完成"
    assert result.model_steps == 2
    assert result.tool_calls == 1
    assert http_attempts == 3
    assert service.calls == [(1, "pending", None)]


def test_loop_with_real_repository_only_returns_authenticated_users_tasks(tmp_path):
    url = f"sqlite+pysqlite:///{(tmp_path / 'agent.db').as_posix()}"
    upgrade_database(url)
    database = Database(url)
    try:
        auth = AuthService(database.sessions, "test-secret-key-at-least-32-bytes")
        user_a = auth.register("agent_user_a", "password-123")
        user_b = auth.register("agent_user_b", "password-123")
        assert user_a is not None and user_b is not None
        service = TaskService(TaskRepository(database.sessions))
        service.create_task(user_a["id"], TaskCreate(title="A 的私有任务"))
        service.create_task(user_b["id"], TaskCreate(title="B 的私有任务"))
        token = auth.login("agent_user_a", "password-123")
        assert token is not None
        trusted_id = auth.user_id_for_token(token)
        seen_tool_result = []

        def handler(request):
            messages = json.loads(request.content)["messages"]
            if len(messages) == 1:
                return httpx.Response(200, json=tool_response())
            seen_tool_result.extend(json.loads(messages[-1]["content"]))
            return httpx.Response(200, json=final_response("找到你的任务"))

        result = run_readonly_agent("查我的任务", user_id=trusted_id,
                                    service=service, settings=SETTINGS,
                                    transport=httpx.MockTransport(handler))
        assert result.answer == "找到你的任务"
        assert [task["title"] for task in seen_tool_result] == ["A 的私有任务"]
    finally:
        database.dispose()
