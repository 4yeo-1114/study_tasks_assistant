import pytest
from fastapi.testclient import TestClient

from web.api import create_app, normalize_database_url
from storage.migration import upgrade_database


def migrated_app(database_location):
    upgrade_database(normalize_database_url(database_location))
    return create_app(database_location, token_secret="test-only-secret-key-at-least-32-bytes")


def authenticated_client(database_location):
    client = TestClient(migrated_app(database_location))
    assert client.post(
        "/auth/register",
        json={"username": "test_user", "password": "test-password-123"},
    ).status_code == 201
    token = client.post(
        "/auth/login", data={"username": "test_user", "password": "test-password-123"}
    ).json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def test_create_app_accepts_sqlalchemy_database_url(tmp_path):

    url = f"sqlite+pysqlite:///{(tmp_path / 'url.db').as_posix()}"
    with authenticated_client(url) as client:
        response = client.post("/tasks", json={"title": "URL 配置"})

    assert response.status_code == 201
    assert response.json()["title"] == "URL 配置"


def test_get_tasks_returns_empty_list(tmp_path):

    client = authenticated_client(tmp_path / "test.db")

    response = client.get("/tasks")

    assert response.status_code == 200
    assert response.json() == []


def test_post_task_persists_and_returns_created_task(tmp_path):

    client = authenticated_client(tmp_path / "test.db")

    response = client.post(
        "/tasks",
        json={"title": "学习 FastAPI", "priority": "high"},
    )

    assert response.status_code == 201
    assert response.json() == {
        "id": 1,
        "title": "学习 FastAPI",
        "status": "pending",
        "priority": "high",
        "due_date": None,
    }
    assert client.get("/tasks").json() == [response.json()]


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "   "},
        {"title": "学习 FastAPI", "priority": "urgent"},
        {"title": "学习 FastAPI", "due_date": "2026-02-30"},
    ],
)
def test_post_task_rejects_invalid_payload_without_writing(tmp_path, payload):

    client = authenticated_client(tmp_path / "test.db")

    response = client.post("/tasks", json=payload)

    assert response.status_code == 422
    assert client.get("/tasks").json() == []


def test_unknown_path_returns_404(tmp_path):

    client = authenticated_client(tmp_path / "test.db")

    response = client.get("/missing")

    assert response.status_code == 404


def test_get_tasks_filters_by_status(tmp_path):

    client = authenticated_client(tmp_path / "test.db")

    response = client.post(
        "/tasks",
        json={"title": "学习ai", "priority": "low"},
    )

    assert response.status_code == 201

    pending_response = client.get("/tasks?status=pending")
    completed_response = client.get("/tasks?status=completed")

    assert pending_response.status_code == 200
    assert pending_response.json() == [
        {
            "id": 1,
            "title": "学习ai",
            "status": "pending",
            "priority": "low",
            "due_date": None,
        }
    ]
    assert completed_response.status_code == 200
    assert completed_response.json() == []


def test_get_task_by_id_returns_created_task(tmp_path):

    client = authenticated_client(tmp_path / "test.db")
    created = client.post(
        "/tasks",
        json={"title": "理解路径参数", "priority": "medium"},
    ).json()

    response = client.get("/tasks/1")

    assert response.status_code == 200
    assert response.json() == created


def test_get_missing_task_returns_404(tmp_path):

    client = authenticated_client(tmp_path / "test.db")

    response = client.get("/tasks/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "找不到任务"}


@pytest.mark.parametrize("path", ["/tasks/not-an-int", "/tasks/0"])
def test_get_task_rejects_invalid_path_id(tmp_path, path):

    client = authenticated_client(tmp_path / "test.db")

    response = client.get(path)

    assert response.status_code == 422


def test_get_tasks_filters_by_priority(tmp_path):

    client = authenticated_client(tmp_path / "test.db")

    created = client.post(
        "/tasks",
        json={"title": "理解路径参数", "priority": "high"},
    ).json()

    client.post(
        "/tasks",
        json={"title": "理解查询参数", "priority": "low"},
    )

    response = client.get("/tasks?priority=high")

    assert response.status_code == 200
    assert response.json() == [created]

    matching_combination = client.get("/tasks?status=pending&priority=high")

    assert matching_combination.status_code == 200
    assert matching_combination.json() == [created]

    response1 = client.get("/tasks?status=completed&priority=high")

    assert response1.status_code == 200
    assert response1.json() == []

    response2 = client.get("/tasks?priority=urgent")

    assert response2.status_code == 422


def test_patch_task_status_persists(tmp_path):

    client = authenticated_client(tmp_path / "test.db")
    client.post("/tasks", json={"title": "学习 PATCH"})

    response = client.patch("/tasks/1", json={"status": "completed"})

    assert response.status_code == 200
    assert response.json() == {
        "id": 1,
        "title": "学习 PATCH",
        "status": "completed",
        "priority": "medium",
        "due_date": None,
    }
    assert client.get("/tasks/1").json()["status"] == "completed"


def test_patch_task_rejects_invalid_status_without_writing(tmp_path):

    client = authenticated_client(tmp_path / "test.db")
    client.post("/tasks", json={"title": "保持 pending"})

    response = client.patch("/tasks/1", json={"status": "invalid"})

    assert response.status_code == 422
    assert client.get("/tasks/1").json()["status"] == "pending"


def test_patch_missing_task_returns_404(tmp_path):

    client = authenticated_client(tmp_path / "test.db")

    response = client.patch("/tasks/999", json={"status": "completed"})

    assert response.status_code == 404
    assert response.json() == {"detail": "找不到任务"}


def test_delete_task_removes_it(tmp_path):

    client = authenticated_client(tmp_path / "test.db")
    client.post("/tasks", json={"title": "待删除任务"})

    response = client.delete("/tasks/1")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/tasks/1").status_code == 404


def test_delete_missing_task_returns_404(tmp_path):

    client = authenticated_client(tmp_path / "test.db")

    response = client.delete("/tasks/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "找不到任务"}


@pytest.mark.parametrize(
    ("method", "path", "json"),
    [
        ("patch", "/tasks/0", {"status": "completed"}),
        ("patch", "/tasks/not-an-int", {"status": "completed"}),
        ("delete", "/tasks/0", None),
        ("delete", "/tasks/not-an-int", None),
    ],
)
def test_write_routes_reject_invalid_task_id(tmp_path, method, path, json):

    client = authenticated_client(tmp_path / "test.db")

    response = client.request(method, path, json=json)

    assert response.status_code == 422


def test_patch_task_status_is_idempotent(tmp_path):

    client = authenticated_client(tmp_path / "test.db")
    client.post("/tasks", json={"title": "学习 PATCH"})
    client.patch("/tasks/1", json={"status": "completed"})
    response = client.patch("/tasks/1", json={"status": "completed"})

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
