from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from api import create_app
from migration import upgrade_database


def client_for(tmp_path):
    url = f"sqlite+pysqlite:///{(tmp_path / 'auth.db').as_posix()}"
    upgrade_database(url)
    return TestClient(create_app(url, token_secret="test-only-secret-key-at-least-32-bytes"))


def register_and_login(client, username):
    registered = client.post(
        "/auth/register", json={"username": username, "password": "strong-password-123"}
    )
    assert registered.status_code == 201
    token = client.post(
        "/auth/login", data={"username": username, "password": "strong-password-123"}
    )
    assert token.status_code == 200
    return {"Authorization": f"Bearer {token.json()['access_token']}"}


def test_register_login_and_invalid_credentials(tmp_path):
    with client_for(tmp_path) as client:
        response = client.post(
            "/auth/register",
            json={"username": " Alice ", "password": "strong-password-123"},
        )
        assert response.status_code == 201
        assert response.json()["username"] == "alice"
        assert "password" not in response.json()
        assert "password_hash" not in response.json()
        assert client.post(
            "/auth/register",
            json={"username": "ALICE", "password": "another-password"},
        ).status_code == 409
        assert client.post(
            "/auth/login", data={"username": "alice", "password": "wrong-password"}
        ).status_code == 401
        assert client.post(
            "/auth/login", data={"username": "missing", "password": "wrong-password"}
        ).status_code == 401
        login = client.post(
            "/auth/login", data={"username": "alice", "password": "strong-password-123"}
        )
        assert login.status_code == 200
        assert login.json()["token_type"] == "bearer"
        assert login.json()["access_token"]


def test_tasks_require_authentication_and_ignore_client_owner_id(tmp_path):
    with client_for(tmp_path) as client:
        assert client.get("/tasks").status_code == 401
        assert client.post("/tasks", json={"title": "x"}).status_code == 401
        assert client.get(
            "/tasks", headers={"Authorization": "Bearer invalid-token"}
        ).status_code == 401
        headers = register_and_login(client, "alice")
        assert client.post(
            "/tasks", json={"title": "x", "owner_id": 999}, headers=headers
        ).status_code == 422


def test_two_users_cannot_read_or_change_each_others_tasks(tmp_path):
    with client_for(tmp_path) as client:
        alice = register_and_login(client, "alice")
        bob = register_and_login(client, "bob")
        created = client.post("/tasks", json={"title": "A 的任务"}, headers=alice)
        assert created.status_code == 201
        task_id = created.json()["id"]
        assert client.get("/tasks", headers=bob).json() == []
        assert client.get(f"/tasks/{task_id}", headers=bob).status_code == 404
        assert client.patch(
            f"/tasks/{task_id}", json={"status": "completed"}, headers=bob
        ).status_code == 404
        assert client.delete(f"/tasks/{task_id}", headers=bob).status_code == 404
        assert client.get(f"/tasks/{task_id}", headers=alice).json() == created.json()
        assert client.patch(
            f"/tasks/{task_id}", json={"status": "completed"}, headers=alice
        ).status_code == 200
        assert client.delete(f"/tasks/{task_id}", headers=alice).status_code == 204


def test_legacy_unowned_tasks_are_preserved_but_hidden(tmp_path):
    url = f"sqlite+pysqlite:///{(tmp_path / 'auth.db').as_posix()}"
    upgrade_database(url)
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO tasks (title,status,priority) "
                "VALUES ('旧任务','pending','medium')"
            ))
    finally:
        engine.dispose()
    with TestClient(create_app(url, token_secret="test-only-secret-key-at-least-32-bytes")) as client:
        alice = register_and_login(client, "alice")
        assert client.get("/tasks", headers=alice).json() == []
        assert client.get("/tasks/1", headers=alice).status_code == 404


def test_expired_token_and_short_secret_are_rejected(tmp_path):
    secret = "test-only-secret-key-at-least-32-bytes"
    url = f"sqlite+pysqlite:///{(tmp_path / 'auth.db').as_posix()}"
    upgrade_database(url)
    with pytest.raises(ValueError, match="32"):
        create_app(url, token_secret="too-short")
    with TestClient(create_app(url, token_secret=secret)) as client:
        register_and_login(client, "alice")
        expired = jwt.encode(
            {"sub": "1", "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
            secret,
            algorithm="HS256",
        )
        assert client.get(
            "/tasks", headers={"Authorization": f"Bearer {expired}"}
        ).status_code == 401
