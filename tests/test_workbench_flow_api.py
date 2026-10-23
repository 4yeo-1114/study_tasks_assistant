"""Backend contract exercised by the UPG-05 workbench without a browser."""

from datetime import date, timedelta

from fastapi.testclient import TestClient

from storage.migration import upgrade_database
from web.api import create_app


def _client(tmp_path) -> TestClient:
    database = tmp_path / "workbench-flow.db"
    upgrade_database(f"sqlite+pysqlite:///{database.as_posix()}")
    client = TestClient(create_app(database, token_secret="test-only-secret-key-at-least-32-bytes"))
    client.post("/auth/register", json={"username": "workbench_user", "password": "test-password-123"})
    token = client.post("/auth/login", data={"username": "workbench_user", "password": "test-password-123"}).json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def _monday() -> date:
    today = date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7)


def test_workbench_core_flow_profile_plan_confirm_task_and_fitness(tmp_path):
    client = _client(tmp_path)
    profile = client.put("/profile", json={
        "learning_goal": "完成后端项目", "training_days_per_week": 3,
        "preferences": "晚间", "limitations": "周三休息", "daily_minutes": 90,
    })
    assert profile.status_code == 200
    monday = _monday()
    proposal = client.post("/plans/weekly", json={
        "week_start": monday.isoformat(), "expected_profile_revision": 1,
        "base_plan_version": 0, "idempotency_key": "workbench-flow-plan",
        "tasks": [
            {"title": "学习 RAG", "task_type": "learning", "due_date": monday.isoformat(), "estimated_minutes": 60},
            {"title": "深蹲训练", "task_type": "fitness", "due_date": (monday + timedelta(days=1)).isoformat(), "estimated_minutes": 40},
        ],
    }).json()
    listed = client.get("/plans")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == proposal["id"]
    confirmed = client.post(f"/plans/{proposal['id']}/confirm")
    assert confirmed.status_code == 200
    first_task = confirmed.json()["tasks"][0]
    assert client.patch(f"/tasks/{first_task['id']}", json={"status": "completed", "actual_minutes": 50}).status_code == 200
    assert client.post("/fitness/workouts", json={
        "workout_date": (monday + timedelta(days=1)).isoformat(),
        "sets": [{"exercise_name": "深蹲", "weight_kg": 50, "reps": 5}],
    }).status_code == 201
    assert client.post("/fitness/weight", json={"recorded_on": monday.isoformat(), "weight_kg": 70.2}).status_code == 201
    progress = client.get("/tasks/progress").json()
    fitness = client.get("/fitness/progress").json()
    assert progress["completed"] == 1
    assert progress["actual_minutes"] == 50
    assert fitness["volume_by_exercise"] == {"深蹲": 250.0}
    assert fitness["exercise_pr"] == {"深蹲": 50.0}
