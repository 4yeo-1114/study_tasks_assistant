"""Deterministic Agent acceptance scenarios backed by the real app and loop."""

import json
from datetime import date, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agent.agent_loop import AgentBudget, AgentBudgetExceededError, AgentStepLimitError, run_readonly_agent
from core.reliability import RetryPolicy
from llm.deepseek_api import DeepSeekAPIError, DeepSeekSettings
from llm.deepseek_tools import DeepSeekToolResponseError
from agent.readonly_tools import ToolArgumentsError
from storage.migration import upgrade_database
from web.api import create_app
from web.schemas import WeeklyPlanCreate


SETTINGS = DeepSeekSettings("scenario-key", "https://api.deepseek.example", "scenario-model")


def _cases():
    cases = []
    cases += [(f"auth_{route}", "unauthorized", route) for route in (
        "profile_read", "profile_write", "session_read", "chat", "plan_create", "task_read",
    )]
    cases += [(f"profile_days_{days}", "profile_days", days) for days in range(-1, 9)]
    cases += [(f"profile_text_{field}_{kind}", "profile_text", (field, kind))
              for field in ("learning_goal", "preferences", "limitations")
              for kind in ("blank", "too_long")]
    cases += [(f"calendar_weekday_{weekday}", "calendar_weekday", weekday) for weekday in range(7)]
    cases += [(f"calendar_offset_{offset}", "calendar_offset", offset) for offset in (-1, 0, 1, 5, 6, 7)]
    cases += [(f"daily_budget_{minutes}", "daily_budget", minutes)
              for minutes in (1, 60, 89, 90, 91, 120, 1440, 1441)]
    cases += [(f"fitness_days_{days}", "fitness_days", days) for days in range(8)]
    cases += [(f"confirm_state_{name}", "confirm_state", name) for name in (
        "first_confirm", "repeat_confirm", "reject_then_confirm", "confirm_then_reject",
        "other_owner_read", "other_owner_confirm", "stale_profile", "stale_plan",
        "missing_profile", "missing_plan",
    )]
    cases += [(f"agent_control_{name}", "agent_control", name) for name in (
        "forbidden_tool", "model_user_id", "retry_once", "retry_exhausted",
        "step_limit_before_tool", "step_limit_after_tool", "tool_budget",
        "duplicate_call_id", "boolean_identity", "zero_identity",
    )]
    cases += [(f"session_{name}", "session", name) for name in (
        "first_turn", "multi_turn", "reopen", "other_owner_read", "other_owner_resume",
        "explicit_profile", "failed_run",
    )]
    return cases


SCENARIOS = _cases()


def _client(tmp_path, username="scenario_owner", runner=None):
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'scenario.db').as_posix()}"
    upgrade_database(database_url)
    app = create_app(database_url, token_secret="scenario-secret-key-at-least-32-bytes",
                     **({"agent_runner": runner, "settings_factory": lambda: SETTINGS} if runner else {}))
    client = TestClient(app)
    client.post("/auth/register", json={"username": username, "password": "scenario-password-123"})
    token = client.post("/auth/login", data={"username": username, "password": "scenario-password-123"}).json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def _profile(client, *, days=3, minutes=90):
    return client.put("/profile", json={
        "learning_goal": "完成项目", "training_days_per_week": days,
        "preferences": "晚间", "limitations": "周三休息", "daily_minutes": minutes,
    })


def _monday():
    today = date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7)


def _plan_payload(start, *, key="scenario-plan", tasks=None):
    return {
        "week_start": start.isoformat(), "expected_profile_revision": 1,
        "base_plan_version": 0, "idempotency_key": key,
        "tasks": tasks or [{"title": "复习 Agent", "task_type": "learning",
                            "due_date": start.isoformat(), "estimated_minutes": 30}],
    }


def _tool_response(call_id="call-1", arguments='{"status":"pending"}', name="list_tasks"):
    return {"choices": [{"finish_reason": "tool_calls", "message": {
        "role": "assistant", "content": None, "tool_calls": [{"id": call_id,
        "type": "function", "function": {"name": name, "arguments": arguments}}]}}]}


def _final(text="done"):
    return {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": text}}]}


@pytest.mark.parametrize("scenario_id,kind,value", SCENARIOS, ids=[case[0] for case in SCENARIOS])
def test_agent_acceptance_scenario(scenario_id, kind, value, tmp_path):
    if kind == "agent_control":
        from tests.test_agent_loop import FakeService

        service = FakeService()
        if value == "forbidden_tool":
            response = _tool_response(name="delete_task")
            with pytest.raises(DeepSeekToolResponseError):
                run_readonly_agent("查任务", user_id=1, service=service, settings=SETTINGS,
                                   transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response)))
            assert service.calls == []
        elif value == "model_user_id":
            response = _tool_response(arguments='{"user_id":999}')
            with pytest.raises(ToolArgumentsError):
                run_readonly_agent("查任务", user_id=1, service=service, settings=SETTINGS,
                                   transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response)))
            assert service.calls == []
        elif value in {"boolean_identity", "zero_identity"}:
            identity = True if value == "boolean_identity" else 0
            with pytest.raises(ValueError):
                run_readonly_agent("查任务", user_id=identity, service=service, settings=SETTINGS,
                                   transport=httpx.MockTransport(lambda _: httpx.Response(200, json=_final())))
        elif value in {"retry_once", "retry_exhausted"}:
            attempts = 0
            def handler(_):
                nonlocal attempts
                attempts += 1
                if value == "retry_once" and attempts == 1:
                    return httpx.Response(503, json={"error": {"message": "retry"}})
                if value == "retry_exhausted":
                    return httpx.Response(503, json={"error": {"message": "retry"}})
                return httpx.Response(200, json=_final())
            if value == "retry_once":
                result = run_readonly_agent("查任务", user_id=1, service=service, settings=SETTINGS,
                    transport=httpx.MockTransport(handler), retry_policy=RetryPolicy(max_attempts=2), sleeper=lambda _: None)
                assert result.answer == "done" and attempts == 2
            else:
                with pytest.raises(DeepSeekAPIError):
                    run_readonly_agent("查任务", user_id=1, service=service, settings=SETTINGS,
                        transport=httpx.MockTransport(handler), retry_policy=RetryPolicy(max_attempts=2), sleeper=lambda _: None)
                assert attempts == 2
        elif value in {"step_limit_before_tool", "step_limit_after_tool"}:
            count = 0
            def handler(_):
                nonlocal count
                count += 1
                return httpx.Response(200, json=_tool_response(f"call-{count}"))
            steps = 1 if value == "step_limit_before_tool" else 2
            with pytest.raises(AgentStepLimitError):
                run_readonly_agent("查任务", user_id=1, service=service, settings=SETTINGS,
                    max_model_steps=steps, transport=httpx.MockTransport(handler))
            assert len(service.calls) == (0 if steps == 1 else 1)
        elif value == "tool_budget":
            calls = 0
            def budget_handler(_):
                nonlocal calls
                calls += 1
                return httpx.Response(200, json=_tool_response(f"budget-{calls}"))
            with pytest.raises(AgentBudgetExceededError):
                run_readonly_agent("查任务", user_id=1, service=service, settings=SETTINGS,
                    budget=AgentBudget(max_tool_calls=1),
                    transport=httpx.MockTransport(budget_handler))
            assert service.calls == [(1, "pending", None)]
        elif value == "duplicate_call_id":
            def handler(_):
                return httpx.Response(200, json=_tool_response("duplicate"))
            with pytest.raises(DeepSeekToolResponseError, match="Call ID 重复"):
                run_readonly_agent("查任务", user_id=1, service=service, settings=SETTINGS,
                    max_model_steps=3, transport=httpx.MockTransport(handler))
            assert len(service.calls) == 1
        return

    if kind == "session":
        requests = []
        def handler(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json=_final("已记录本轮对话"))
        def runner(question, **kwargs):
            return run_readonly_agent(question, **kwargs, transport=httpx.MockTransport(handler))
        client = _client(tmp_path, runner=runner)
        if value == "explicit_profile":
            assert _profile(client).status_code == 200
            before = client.get("/profile").json()
        first = client.post("/agent/chat", json={"message": "以后每天训练七小时"})
        assert first.status_code == 200
        session_id = first.json()["session_id"]
        if value in {"other_owner_read", "other_owner_resume"}:
            other = _client(tmp_path, "session_other", runner)
            response = (other.get(f"/agent/sessions/{session_id}") if value == "other_owner_read"
                        else other.post("/agent/chat", json={"message": "窃取上下文", "session_id": session_id}))
            assert response.status_code == 404
            assert len(requests) == 1
        elif value in {"multi_turn", "reopen"}:
            if value == "reopen":
                client = _client(tmp_path, runner=runner)
            second = client.post("/agent/chat", json={"message": "改为每周三次", "session_id": session_id})
            assert second.status_code == 200 and second.json()["run_id"] != first.json()["run_id"]
            messages = requests[-1]["messages"]
            assert [(m["role"], m["content"]) for m in messages if m["role"] != "system"] == [
                ("user", "以后每天训练七小时"), ("assistant", "已记录本轮对话"), ("user", "改为每周三次")]
        elif value == "explicit_profile":
            assert client.get("/profile").json() == before
        elif value == "failed_run":
            def failing_runner(*args, **kwargs):
                raise AgentBudgetExceededError("budget exhausted")
            client = _client(tmp_path, runner=failing_runner)
            failed = client.post("/agent/chat", json={"message": "失败轮次", "session_id": session_id})
            assert failed.status_code == 429
        detail = client.get(f"/agent/sessions/{session_id}")
        assert detail.status_code == 200
        data = detail.json()
        turn_count = 2 if value in {"multi_turn", "reopen"} else 1
        assert [m["sequence"] for m in data["messages"]] == list(range(1, turn_count * 2 + 1))
        assert [m["role"] for m in data["messages"]] == ["user", "assistant"] * turn_count
        assert [r["status"] for r in data["runs"]] == (["succeeded", "failed"] if value == "failed_run" else ["succeeded"] * turn_count)
        return

    client = _client(tmp_path)
    if kind == "unauthorized":
        client.headers.pop("Authorization")
        routes = {
            "profile_read": ("GET", "/profile", None),
            "profile_write": ("PUT", "/profile", {"learning_goal": "x"}),
            "session_read": ("GET", "/agent/sessions/not-owned", None),
            "chat": ("POST", "/agent/chat", {"message": "hello"}),
            "plan_create": ("POST", "/plans/weekly", _plan_payload(_monday())),
            "task_read": ("GET", "/tasks", None),
        }
        method, path, body = routes[value]
        response = client.request(method, path, json=body)
        assert response.status_code == 401
    elif kind == "profile_days":
        response = _profile(client, days=value)
        assert response.status_code == (422 if value < 0 or value > 7 else 200)
    elif kind == "profile_text":
        field, invalid_kind = value
        payload = {"learning_goal": "目标", "training_days_per_week": 3,
                   "preferences": "偏好", "limitations": "限制", "daily_minutes": 90}
        payload[field] = " " if invalid_kind == "blank" else "x" * (501 if field == "learning_goal" else 2001)
        response = client.put("/profile", json=payload)
        assert response.status_code == 422
    elif kind == "calendar_weekday":
        _profile(client)
        start = _monday() + timedelta(days=value)
        response = client.post("/plans/weekly", json=_plan_payload(start))
        assert response.status_code == (422 if value != 0 else 201)
    elif kind == "calendar_offset":
        start = _monday()
        payload = _plan_payload(start, tasks=[{"title": "复习 Agent", "task_type": "learning",
            "due_date": (start + timedelta(days=value)).isoformat(), "estimated_minutes": 30}])
        if value in (-1, 7):
            with pytest.raises(ValidationError):
                WeeklyPlanCreate.model_validate(payload)
        else:
            parsed = WeeklyPlanCreate.model_validate(payload)
            assert parsed.week_start == start
    elif kind == "daily_budget":
        _profile(client, minutes=90)
        payload = _plan_payload(_monday(), tasks=[{"title": "复习 Agent", "task_type": "learning",
            "due_date": _monday().isoformat(), "estimated_minutes": value}])
        response = client.post("/plans/weekly", json=payload)
        assert response.status_code == (422 if value > 90 else 201)
        assert client.get("/tasks").json() == []
    elif kind == "fitness_days":
        _profile(client, days=3)
        start = _monday()
        tasks = [{"title": f"训练第 {day + 1} 天", "task_type": "fitness",
                  "due_date": (start + timedelta(days=day)).isoformat(), "estimated_minutes": 20}
                 for day in range(value)]
        response = client.post("/plans/weekly", json=_plan_payload(start, tasks=tasks or [
            {"title": "休息", "task_type": "learning", "due_date": start.isoformat(), "estimated_minutes": 20}
        ]))
        assert response.status_code == (422 if value > 3 else 201)
    elif kind == "confirm_state":
        _profile(client)
        start = _monday()
        proposal = client.post("/plans/weekly", json=_plan_payload(start)).json()
        plan_id = proposal["id"]
        if value in {"first_confirm", "repeat_confirm"}:
            first = client.post(f"/plans/{plan_id}/confirm")
            assert first.status_code == 200 and first.json()["status"] == "confirmed"
            if value == "repeat_confirm":
                again = client.post(f"/plans/{plan_id}/confirm")
                assert again.json() == first.json() and len(client.get("/tasks").json()) == 1
        elif value in {"reject_then_confirm", "confirm_then_reject"}:
            if value == "reject_then_confirm":
                client.post(f"/plans/{plan_id}/reject")
                assert client.post(f"/plans/{plan_id}/confirm").status_code == 409
                assert client.get("/tasks").json() == []
            else:
                client.post(f"/plans/{plan_id}/confirm")
                assert client.post(f"/plans/{plan_id}/reject").status_code == 409
        elif value.startswith("other_owner"):
            other = _client(tmp_path, "scenario_other")
            response = other.get(f"/plans/{plan_id}") if value == "other_owner_read" else other.post(f"/plans/{plan_id}/confirm")
            assert response.status_code == 404 and client.get("/tasks").json() == []
        elif value in {"stale_profile", "stale_plan"}:
            if value == "stale_plan":
                second = client.post("/plans/weekly", json=_plan_payload(start, key="second")).json()
                client.post(f"/plans/{plan_id}/confirm")
                assert client.post(f"/plans/{second['id']}/confirm").status_code == 409
            else:
                client.put("/profile", json={"learning_goal": "更新", "training_days_per_week": 3,
                    "preferences": "偏好", "limitations": "限制", "daily_minutes": 90})
                assert client.post(f"/plans/{plan_id}/confirm").status_code == 409
        elif value == "missing_profile":
            client.delete("/profile")
            assert client.post(f"/plans/{plan_id}/confirm").status_code == 409
        else:
            assert client.get("/plans/missing-plan").status_code == 404


def test_agent_scenario_dataset_has_required_coverage():
    assert len(SCENARIOS) >= 60
    assert len({case[0] for case in SCENARIOS}) == len(SCENARIOS)
    categories = {case[1] for case in SCENARIOS}
    assert {"unauthorized", "profile_days", "calendar_weekday", "daily_budget",
            "fitness_days", "confirm_state", "agent_control", "session"} <= categories

