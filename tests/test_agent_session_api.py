from fastapi.testclient import TestClient

from agent.agent_loop import AgentAnswer
from storage.migration import upgrade_database
from web.api import create_app


def _client_for(tmp_path, username: str, runner=None) -> TestClient:
    database = tmp_path / "agent-sessions.db"
    upgrade_database(f"sqlite+pysqlite:///{database.as_posix()}")
    app = create_app(
        database,
        token_secret="test-only-secret-key-at-least-32-bytes",
        agent_runner=runner or (lambda message, **_: AgentAnswer(f"已处理：{message}", 1, 0)),
        settings_factory=lambda: object(),
    )
    client = TestClient(app)
    client.post("/auth/register", json={"username": username, "password": "test-password-123"})
    token = client.post("/auth/login", data={"username": username, "password": "test-password-123"}).json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def test_agent_chat_persists_and_resumes_an_owner_scoped_session(tmp_path):
    owner = _client_for(tmp_path, "session_owner")
    other = _client_for(tmp_path, "session_other")

    first = owner.post("/agent/chat", json={"message": "安排今天的复习"})

    assert first.status_code == 200
    session_id = first.json()["session_id"]
    assert first.json()["run_id"]
    assert other.get(f"/agent/sessions/{session_id}").status_code == 404

    second = owner.post(
        "/agent/chat",
        json={"message": "补充训练安排", "session_id": session_id},
    )

    assert second.status_code == 200
    assert second.json()["session_id"] == session_id
    restored = owner.get(f"/agent/sessions/{session_id}")
    assert restored.status_code == 200
    assert [message["role"] for message in restored.json()["messages"]] == [
        "user", "assistant", "user", "assistant",
    ]
    assert {run["status"] for run in restored.json()["runs"]} == {"succeeded"}


def test_resumed_chat_passes_previous_messages_to_runner(tmp_path):
    received = []

    def runner(message, **kwargs):
        received.append(kwargs.get("history"))
        return AgentAnswer("answer", 1, 0)

    client = _client_for(tmp_path, "history_owner", runner)
    first = client.post("/agent/chat", json={"message": "first"}).json()
    second = client.post("/agent/chat", json={"message": "second", "session_id": first["session_id"]})

    assert second.status_code == 200
    assert received == [[], [{"role": "user", "content": "first"}, {"role": "assistant", "content": "answer"}]]


def test_another_owner_cannot_resume_a_session_thread(tmp_path):
    owner = _client_for(tmp_path, "thread_owner")
    other = _client_for(tmp_path, "thread_other")
    first = owner.post("/agent/chat", json={"message": "first"}).json()

    response = other.post("/agent/chat", json={
        "message": "attempt cross-owner resume", "session_id": first["session_id"],
    })

    assert response.status_code == 404
