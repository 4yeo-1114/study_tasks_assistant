"""Exercise real interrupt/resume, including reopening the checkpoint database."""

import pytest

from agent.persistent_runtime import create_checkpoint_store
from agent.plan_approval import PlanApprovalWorkflow
from tests.test_weekly_plan_api import _client, _payload, _profile, _week_start
from weekly_plans.service import WeeklyPlanConflictError, WeeklyPlanNotFoundError, WeeklyPlanService


def test_plan_waits_then_resumes_after_checkpoint_store_reopen(tmp_path):
    client = _client(tmp_path, "approval_owner")
    _profile(client)
    plan = client.post("/plans/weekly", json=_payload(_week_start())).json()
    service = WeeklyPlanService(client.app.state.database.sessions)
    path = tmp_path / "isolated-checkpoints.db"
    store = create_checkpoint_store(path)
    flow = PlanApprovalWorkflow(service, store.saver)
    try:
        waiting = flow.wait(1, plan["id"])
        assert waiting["waiting_for_confirmation"] is True
        assert client.get("/tasks").json() == []
    finally:
        store.close()
    store = create_checkpoint_store(path)
    try:
        flow = PlanApprovalWorkflow(service, store.saver)
        assert flow.wait(1, plan["id"]) == waiting
        result = flow.decide(1, plan["id"], "confirm")
        assert result["status"] == "confirmed"
        assert flow.decide(1, plan["id"], "confirm") == result
        assert len(client.get("/tasks").json()) == 2
        assert flow.wait(1, plan["id"])["waiting_for_confirmation"] is False
        with pytest.raises(WeeklyPlanConflictError):
            flow.decide(1, plan["id"], "reject")
    finally:
        store.close()


def test_resume_checks_owner_and_current_profile(tmp_path):
    client = _client(tmp_path, "approval_owner")
    _profile(client)
    plan = client.post("/plans/weekly", json=_payload(_week_start())).json()
    service = WeeklyPlanService(client.app.state.database.sessions)
    store = create_checkpoint_store(tmp_path / "approval.db")
    try:
        flow = PlanApprovalWorkflow(service, store.saver)
        flow.wait(1, plan["id"])
        with pytest.raises(WeeklyPlanNotFoundError):
            flow.decide(2, plan["id"], "confirm")
        _profile(client, minutes=10)
        with pytest.raises(WeeklyPlanConflictError):
            flow.decide(1, plan["id"], "confirm")
        assert client.get("/tasks").json() == []
        assert flow.decide(1, plan["id"], "reject")["status"] == "rejected"
        assert flow.wait(1, plan["id"])["waiting_for_confirmation"] is False
        assert client.get("/tasks").json() == []
    finally:
        store.close()


def test_api_exposes_wait_and_reject_without_creating_tasks(tmp_path):
    client = _client(tmp_path, "approval_owner")
    _profile(client)
    plan = client.post("/plans/weekly", json=_payload(_week_start())).json()
    response = client.get(f"/plans/{plan['id']}/workflow")
    assert response.status_code == 200
    assert response.json()["waiting_for_confirmation"] is True
    assert client.post(f"/plans/{plan['id']}/reject").json()["status"] == "rejected"
    assert client.get(f"/plans/{plan['id']}/workflow").json()["waiting_for_confirmation"] is False
    assert client.get("/tasks").json() == []
