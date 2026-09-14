import pytest
from fastapi.testclient import TestClient


def test_get_tasks_returns_empty_list(tmp_path):
    from api import create_app

    client = TestClient(create_app(tmp_path / "test.db"))

    response = client.get("/tasks")

    assert response.status_code == 200
    assert response.json() == []


def test_post_task_persists_and_returns_created_task(tmp_path):
    from api import create_app

    client = TestClient(create_app(tmp_path / "test.db"))

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
    from api import create_app

    client = TestClient(create_app(tmp_path / "test.db"))

    response = client.post("/tasks", json=payload)

    assert response.status_code == 422
    assert client.get("/tasks").json() == []


def test_unknown_path_returns_404(tmp_path):
    from api import create_app

    client = TestClient(create_app(tmp_path / "test.db"))

    response = client.get("/missing")

    assert response.status_code == 404


def test_get_tasks_filters_by_status(tmp_path):
    from api import create_app

    client = TestClient(create_app(tmp_path / "test.db"))

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
