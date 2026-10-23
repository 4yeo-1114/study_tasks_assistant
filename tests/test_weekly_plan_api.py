from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from storage.migration import upgrade_database
from web.api import create_app


def _client(tmp_path, username: str) -> TestClient:
    database = tmp_path / "weekly-plans.db"
    upgrade_database(f"sqlite+pysqlite:///{database.as_posix()}")
    client = TestClient(create_app(database, token_secret="test-only-secret-key-at-least-32-bytes"))
    client.post("/auth/register", json={"username": username, "password": "test-password-123"})
    token = client.post("/auth/login", data={"username": username, "password": "test-password-123"}).json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def _week_start() -> date:
    today = date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7)


def _profile(client, *, days=3, minutes=90):
    return client.put("/profile", json={
        "learning_goal": "完成项目",
        "training_days_per_week": days,
        "preferences": "晚间安排",
        "limitations": "周三休息",
        "daily_minutes": minutes,
    }).json()


def _payload(start: date, key="week-1"):
    return {
        "week_start": start.isoformat(),
        "expected_profile_revision": 1,
        "base_plan_version": 0,
        "idempotency_key": key,
        "tasks": [
            {"title": "阅读检索设计", "task_type": "learning", "due_date": start.isoformat(), "estimated_minutes": 60},
            {"title": "力量训练", "task_type": "fitness", "due_date": (start + timedelta(days=1)).isoformat(), "estimated_minutes": 50},
        ],
    }


def test_weekly_plan_proposal_writes_no_tasks_until_confirm_and_confirm_is_idempotent(tmp_path):
    client = _client(tmp_path, "plan_owner")
    _profile(client)
    payload = _payload(_week_start())

    proposed = client.post("/plans/weekly", json=payload)

    assert proposed.status_code == 201
    proposal = proposed.json()
    assert proposal["status"] == "pending"
    assert proposal["plan_version"] is None
    assert client.get("/tasks").json() == []

    confirmed = client.post(f"/plans/{proposal['id']}/confirm")
    repeated = client.post(f"/plans/{proposal['id']}/confirm")

    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
    assert confirmed.json()["plan_version"] == 1
    assert len(confirmed.json()["tasks"]) == 2
    assert repeated.json() == confirmed.json()
    assert len(client.get("/tasks").json()) == 2
    assert client.get("/plans/current", params={"week_start": payload["week_start"]}).json()["plan_version"] == 1


@pytest.mark.parametrize(
    "days,minutes,tasks,detail_part",
    [
        (3, 90, [
            {"title": "a", "task_type": "learning", "day": 0, "minutes": 60},
            {"title": "b", "task_type": "fitness", "day": 0, "minutes": 40},
        ], "预算"),
        (1, 90, [
            {"title": "a", "task_type": "fitness", "day": 0, "minutes": 20},
            {"title": "b", "task_type": "fitness", "day": 1, "minutes": 20},
        ], "训练"),
    ],
)
def test_weekly_plan_rejects_daily_budget_or_training_frequency_violations(
    tmp_path, days, minutes, tasks, detail_part
):
    client = _client(tmp_path, f"plan_limit_{days}_{minutes}")
    _profile(client, days=days, minutes=minutes)
    start = _week_start()
    payload = _payload(start)
    payload["tasks"] = [
        {"title": row["title"], "task_type": row["task_type"],
         "due_date": (start + timedelta(days=row["day"])).isoformat(),
         "estimated_minutes": row["minutes"]}
        for row in tasks
    ]

    response = client.post("/plans/weekly", json=payload)

    assert response.status_code == 422
    assert detail_part in response.json()["detail"]
    assert client.get("/tasks").json() == []


def test_old_profile_revision_and_old_plan_version_cannot_confirm(tmp_path):
    client = _client(tmp_path, "plan_conflicts")
    profile = _profile(client)
    start = _week_start()
    first = client.post("/plans/weekly", json=_payload(start, "first")).json()
    second_payload = _payload(start, "second")
    second_payload["base_plan_version"] = 0
    second = client.post("/plans/weekly", json=second_payload).json()
    client.post(f"/plans/{first['id']}/confirm")

    stale_plan = client.post(f"/plans/{second['id']}/confirm")
    assert stale_plan.status_code == 409

    third_payload = _payload(start, "third")
    third_payload["base_plan_version"] = 1
    third = client.post("/plans/weekly", json=third_payload).json()
    changed = client.put("/profile", json={
        "learning_goal": "更新目标", "training_days_per_week": 3,
        "preferences": "偏好", "limitations": "限制", "daily_minutes": 90,
    })
    assert changed.json()["revision"] == profile["revision"] + 1
    stale_profile = client.post(f"/plans/{third['id']}/confirm")

    assert stale_profile.status_code == 409
    assert len(client.get("/tasks").json()) == 2


def test_weekly_plan_is_owner_scoped_and_idempotency_key_conflicts_on_changed_payload(tmp_path):
    owner = _client(tmp_path, "plan_scope_owner")
    other = _client(tmp_path, "plan_scope_other")
    _profile(owner)
    proposal = owner.post("/plans/weekly", json=_payload(_week_start())).json()

    assert other.get(f"/plans/{proposal['id']}").status_code == 404
    changed = _payload(_week_start())
    changed["tasks"][0]["title"] = "另一个提案"
    conflict = owner.post("/plans/weekly", json=changed)

    assert conflict.status_code == 409
    assert owner.post(f"/plans/{proposal['id']}/reject").json()["status"] == "rejected"
    assert owner.post(f"/plans/{proposal['id']}/confirm").status_code == 409
    assert owner.get("/tasks").json() == []


def test_weekly_plan_list_is_owner_scoped_and_newest_first(tmp_path):
    owner = _client(tmp_path, "plan_list_owner")
    other = _client(tmp_path, "plan_list_other")
    _profile(owner)
    first = owner.post("/plans/weekly", json=_payload(_week_start(), "list-first")).json()
    second = owner.post("/plans/weekly", json=_payload(_week_start() + timedelta(days=7), "list-second")).json()

    response = owner.get("/plans")

    assert response.status_code == 200
    assert [plan["id"] for plan in response.json()] == [second["id"], first["id"]]
    assert other.get("/plans").json() == []


def test_weekly_plan_confirmation_rolls_back_tasks_when_batch_insert_fails(tmp_path, monkeypatch):
    client = _client(tmp_path, "plan_rollback")
    _profile(client)
    proposal = client.post("/plans/weekly", json=_payload(_week_start())).json()
    database = client.app.state.database
    injected = False

    def fail_task_insert(conn, cursor, statement, parameters, context, executemany):
        nonlocal injected
        if not injected and statement.lstrip().upper().startswith("INSERT INTO TASKS"):
            injected = True
            raise RuntimeError("simulated batch failure")

    event.listen(database.engine, "before_cursor_execute", fail_task_insert)
    with pytest.raises(RuntimeError, match="simulated batch failure"):
        client.post(f"/plans/{proposal['id']}/confirm")
    event.remove(database.engine, "before_cursor_execute", fail_task_insert)

    assert client.get("/tasks").json() == []
    assert client.get(f"/plans/{proposal['id']}").json()["status"] == "pending"


def test_adjustment_carries_only_pending_tasks_and_reports_workout_evidence(tmp_path):
    client = _client(tmp_path, "plan_adjustment")
    _profile(client)
    source_start = _week_start()
    payload = _payload(source_start, "source-plan")
    payload["tasks"].append({
        "title": "复习 SQL", "task_type": "learning",
        "due_date": (source_start + timedelta(days=2)).isoformat(), "estimated_minutes": 30,
    })
    source = client.post("/plans/weekly", json=payload).json()
    confirmed = client.post(f"/plans/{source['id']}/confirm").json()
    completed_id = next(task["id"] for task in confirmed["tasks"] if task["title"] == "阅读检索设计")
    client.patch(f"/tasks/{completed_id}", json={"status": "completed", "actual_minutes": 45})
    client.post("/fitness/workouts", json={
        "workout_date": (source_start + timedelta(days=1)).isoformat(),
        "sets": [{"exercise_name": "深蹲", "weight_kg": 40, "reps": 8}],
    })

    adjusted = client.post(f"/plans/{source['id']}/adjust", json={"idempotency_key": "adjust-1"})

    assert adjusted.status_code == 201
    proposal = adjusted.json()
    assert proposal["status"] == "pending"
    assert proposal["week_start"] == (source_start + timedelta(days=7)).isoformat()
    assert [task["title"] for task in proposal["tasks"]] == ["力量训练", "复习 SQL"]
    assert [task["due_date"] for task in proposal["tasks"]] == [
        (source_start + timedelta(days=8)).isoformat(),
        (source_start + timedelta(days=9)).isoformat(),
    ]
    assert "Completed tasks excluded: 1" in proposal["adjustment_summary"]
    assert "workout sessions in source week: 1" in proposal["adjustment_summary"]
    assert len(client.get("/tasks").json()) == 3

    confirmed_adjustment = client.post(f"/plans/{proposal['id']}/confirm")
    assert confirmed_adjustment.status_code == 200
    assert len(client.get("/tasks").json()) == 5


def test_adjustment_requires_confirmed_plan_and_is_idempotent(tmp_path):
    client = _client(tmp_path, "plan_adjustment_state")
    _profile(client)
    source = client.post("/plans/weekly", json=_payload(_week_start())).json()

    pending = client.post(f"/plans/{source['id']}/adjust", json={"idempotency_key": "adjust-pending"})
    assert pending.status_code == 409

    client.post(f"/plans/{source['id']}/confirm")
    first = client.post(f"/plans/{source['id']}/adjust", json={"idempotency_key": "adjust-idem"})
    second = client.post(f"/plans/{source['id']}/adjust", json={"idempotency_key": "adjust-idem"})
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json() == first.json()
