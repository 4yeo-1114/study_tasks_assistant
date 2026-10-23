from fastapi.testclient import TestClient

from storage.migration import upgrade_database
from web.api import create_app


def _client_for(tmp_path, username: str) -> TestClient:
    database = tmp_path / "profiles.db"
    upgrade_database(f"sqlite+pysqlite:///{database.as_posix()}")
    client = TestClient(create_app(database, token_secret="test-only-secret-key-at-least-32-bytes"))
    client.post("/auth/register", json={"username": username, "password": "test-password-123"})
    token = client.post("/auth/login", data={"username": username, "password": "test-password-123"}).json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def test_profile_is_explicit_versioned_and_owner_scoped(tmp_path):
    owner = _client_for(tmp_path, "profile_owner")
    other = _client_for(tmp_path, "profile_other")
    payload = {
        "learning_goal": "完成 Agent 后端项目",
        "training_days_per_week": 3,
        "preferences": "晚上学习，力量训练优先",
        "limitations": "周三不能训练",
        "daily_minutes": 90,
    }

    created = owner.put("/profile", json=payload)

    assert created.status_code == 200
    assert created.json() == {**payload, "revision": 1, "plan_version": 0}
    assert other.get("/profile").status_code == 404

    changed = owner.put("/profile", json={**payload, "daily_minutes": 120})

    assert changed.status_code == 200
    assert changed.json()["daily_minutes"] == 120
    assert changed.json()["revision"] == 2
    assert owner.delete("/profile").status_code == 204
    assert owner.get("/profile").status_code == 404
