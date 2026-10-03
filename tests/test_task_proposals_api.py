from fastapi.testclient import TestClient

import api
from api import create_app
from deepseek_tools import ToolCallProposal
from migration import upgrade_database
from task_proposals import TaskProposalService


def test_confirmation_endpoint_requires_owner_and_is_idempotent(tmp_path):
    url = f"sqlite+pysqlite:///{(tmp_path / 'api.db').as_posix()}"
    upgrade_database(url)
    app = create_app(url, token_secret="test-secret-key-at-least-32-bytes")
    try:
        with TestClient(app) as client:
            for name in ("alice", "bob"):
                response = client.post("/auth/register", json={
                    "username": name, "password": "password-123"
                })
                assert response.status_code == 201
            alice_token = client.post("/auth/login", data={
                "username": "alice", "password": "password-123"
            }).json()["access_token"]
            bob_token = client.post("/auth/login", data={
                "username": "bob", "password": "password-123"
            }).json()["access_token"]
            alice = {"Authorization": f"Bearer {alice_token}"}
            bob = {"Authorization": f"Bearer {bob_token}"}
            service = TaskProposalService(app.state.database.sessions)
            proposal = service.propose_from_call(1, ToolCallProposal(
                "model-call", "create_task", {"title": "确认任务"}
            ))
            path = f"/agent/task-proposals/{proposal['id']}"

            assert client.post(path + "/confirm").status_code == 401
            assert client.get(path, headers=bob).status_code == 404
            assert client.post(path + "/confirm", headers=bob).status_code == 404
            assert client.get("/tasks", headers=alice).json() == []
            preview = client.get(path, headers=alice)
            assert preview.status_code == 200
            assert preview.json()["status"] == "pending"

            first = client.post(path + "/confirm", headers=alice)
            second = client.post(path + "/confirm", headers=alice)
            assert first.status_code == second.status_code == 200
            assert first.json() == second.json()
            assert len(client.get("/tasks", headers=alice).json()) == 1
            assert client.get("/tasks", headers=bob).json() == []
    finally:
        app.state.database.dispose()


def test_model_proposal_endpoint_never_writes_without_confirmation(tmp_path, monkeypatch):
    url = f"sqlite+pysqlite:///{(tmp_path / 'api.db').as_posix()}"
    upgrade_database(url)
    app = create_app(url, token_secret="test-secret-key-at-least-32-bytes")
    try:
        with TestClient(app) as client:
            assert client.post("/auth/register", json={
                "username": "alice", "password": "password-123"
            }).status_code == 201
            token = client.post("/auth/login", data={
                "username": "alice", "password": "password-123"
            }).json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            def fake_model(question, *, user_id, service, settings):
                assert question == "明天复习 SQL"
                return service.propose_from_call(user_id, ToolCallProposal(
                    "call-1", "create_task", {"title": "复习 SQL"}
                ))

            monkeypatch.setattr(api, "propose_task_from_model", fake_model)
            monkeypatch.setattr(api.DeepSeekSettings, "from_env", lambda: object())
            assert client.post("/agent/task-proposals", json={
                "question": "明天复习 SQL"
            }).status_code == 401
            response = client.post("/agent/task-proposals", headers=headers, json={
                "question": "明天复习 SQL"
            })
            assert response.status_code == 201
            assert response.json()["status"] == "pending"
            assert client.get("/tasks", headers=headers).json() == []
    finally:
        app.state.database.dispose()
