from fastapi.testclient import TestClient

from storage.migration import upgrade_database
from web.api import create_app


def client_for(tmp_path):
    database = tmp_path / "task-progress.db"
    upgrade_database(f"sqlite+pysqlite:///{database.as_posix()}")
    client = TestClient(create_app(database, token_secret="test-only-secret-key-at-least-32-bytes"))
    client.post("/auth/register", json={"username": "progress_user", "password": "test-password-123"})
    token = client.post("/auth/login", data={"username": "progress_user", "password": "test-password-123"}).json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def test_task_progress_reports_completion_and_time_variance(tmp_path):
    client = client_for(tmp_path)
    first = client.post("/tasks", json={"title": "学习", "task_type": "learning", "estimated_minutes": 30}).json()
    second = client.post("/tasks", json={"title": "训练", "task_type": "fitness", "estimated_minutes": 45}).json()
    client.patch(f"/tasks/{first['id']}", json={"status": "completed", "actual_minutes": 35})
    result = client.get("/tasks/progress")
    assert result.status_code == 200
    assert result.json() == {"total": 2, "completed": 1, "pending": 1, "estimated_minutes": 75, "actual_minutes": 35, "completion_rate": 0.5, "time_variance_minutes": -40}
