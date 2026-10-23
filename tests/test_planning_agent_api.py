import json

import httpx
import pytest

from agent.agent_loop import run_readonly_agent
from tests.test_agent_scenario_suite import SETTINGS, _client, _final, _monday, _profile, _tool_response


@pytest.mark.parametrize("mode", ["valid", "identity", "over_budget", "missing_profile"])
def test_chat_generates_only_an_authorized_pending_weekly_plan(tmp_path, mode):
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        tool_messages = [m for m in body["messages"] if m["role"] == "tool"]
        if not tool_messages:
            response = _tool_response("context", "{}", "get_planning_context")
        elif len(tool_messages) == 1:
            args = {"week_start": _monday().isoformat(), "tasks": [{
                "title": "学习事务", "task_type": "learning", "due_date": _monday().isoformat(),
                "estimated_minutes": 100 if mode == "over_budget" else 30}]}
            if mode == "identity":
                args["owner_id"] = 999
            response = _tool_response("plan", json.dumps(args), "propose_weekly_plan")
        else:
            proposal = json.loads(tool_messages[-1]["content"])
            assert proposal["status"] == "pending"
            response = _final("周计划已生成，请确认")
        return httpx.Response(200, json=response)

    def runner(question, **kwargs):
        return run_readonly_agent(question, **kwargs, transport=httpx.MockTransport(handler))

    client = _client(tmp_path, runner=runner)
    if mode != "missing_profile":
        assert _profile(client).status_code == 200
    response = client.post("/agent/chat", json={"message": "安排下周学习和训练", "idempotency_key": "chat-week-1"})
    assert response.status_code == (200 if mode == "valid" else 422), response.text
    assert len(calls) == (3 if mode == "valid" else 2)
    assert client.get("/tasks").json() == []
    if mode == "valid":
        plan = response.json()["pending_plans"][0]
        assert plan["status"] == "pending" and plan["expected_profile_revision"] == 1
        session_id = response.json()["session_id"]
        # Same key and payload across requests reuse the persisted proposal.
        again = client.post("/agent/chat", json={"message": "安排下周学习和训练", "session_id": session_id,
                                                "idempotency_key": "chat-week-1"})
        assert again.status_code == 200
        assert again.json()["pending_plans"][0]["id"] == plan["id"]
        assert client.post(f"/plans/{plan['id']}/confirm").status_code == 200
        assert len(client.get("/tasks").json()) == 1
