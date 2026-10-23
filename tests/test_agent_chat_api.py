from fastapi.testclient import TestClient

from agent.agent_loop import (
    AgentAnswer,
    AgentBudgetExceededError,
    AgentState,
    AgentTraceEvent,
)
from web.api import create_app
from llm.deepseek_tools import ToolCallProposal
from storage.migration import upgrade_database
from knowledge.knowledge_runtime import KnowledgeRuntimeError


def authenticated_client(tmp_path, runner):
    url = f"sqlite+pysqlite:///{(tmp_path / 'agent-api.db').as_posix()}"
    upgrade_database(url)
    app = create_app(
        url,
        token_secret="test-secret-key-at-least-32-bytes",
        agent_runner=runner,
        settings_factory=lambda: object(),
    )
    client = TestClient(app)
    client.post("/auth/register", json={
        "username": "alice", "password": "password-123",
    })
    token = client.post("/auth/login", data={
        "username": "alice", "password": "password-123",
    }).json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def test_agent_chat_creates_a_fresh_knowledge_executor_per_request(tmp_path):
    executors = []
    received = []

    def executor_factory():
        executor = object()
        executors.append(executor)
        return executor

    def runner(question, *, knowledge_executor, **kwargs):
        received.append(knowledge_executor)
        return AgentAnswer("ok", 1, 0, 1, ())

    url = f"sqlite+pysqlite:///{(tmp_path / 'agent-runtime.db').as_posix()}"
    upgrade_database(url)
    app = create_app(
        url,
        token_secret="test-secret-key-at-least-32-bytes",
        agent_runner=runner,
        settings_factory=lambda: object(),
        knowledge_executor_factory=executor_factory,
    )
    with TestClient(app) as client:
        client.post("/auth/register", json={
            "username": "alice", "password": "password-123",
        })
        token = client.post("/auth/login", data={
            "username": "alice", "password": "password-123",
        }).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        client.post("/agent/chat", json={"message": "first"}, headers=headers)
        client.post("/agent/chat", json={"message": "second"}, headers=headers)

    assert received == executors
    assert len(executors) == 2
    assert executors[0] is not executors[1]


def test_agent_chat_returns_public_trace_and_pending_proposal(tmp_path):
    def runner(question, *, user_id, proposal_service, **kwargs):
        proposal = proposal_service.propose_from_call(
            user_id,
            ToolCallProposal("call-create", "create_task", {"title": "复习 Agent"}),
            idempotency_key="request-1",
        )
        trace = (
            AgentTraceEvent("private-run-id", 0, AgentState.RECEIVED, "question_received"),
            AgentTraceEvent(
                "private-run-id", 1, AgentState.EXECUTING, "proposal_created",
                tool_call_id="call-create", proposal_id=proposal["id"],
            ),
            AgentTraceEvent("private-run-id", 2, AgentState.COMPLETED, "answer_completed"),
        )
        return AgentAnswer("提案已创建，等待确认。", 2, 1, 20, trace)

    with authenticated_client(tmp_path, runner) as client:
        response = client.post("/agent/chat", json={"message": "创建复习任务"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "提案已创建，等待确认。"
    assert body["pending_proposals"][0]["status"] == "pending"
    assert body["trace"][1]["proposal_id"] == body["pending_proposals"][0]["id"]
    assert "run_id" not in body["trace"][0]


def test_agent_chat_public_trace_includes_tool_name(tmp_path):
    def runner(question, **kwargs):
        trace = (
            AgentTraceEvent("private-run-id", 0, AgentState.RECEIVED, "question_received"),
            AgentTraceEvent(
                "private-run-id", 1, AgentState.EXECUTING, "tool_execution_started",
                tool_call_id="call-list", tool_name="list_tasks",
            ),
            AgentTraceEvent("private-run-id", 2, AgentState.COMPLETED, "answer_completed"),
        )
        return AgentAnswer("查询完成", 2, 1, 10, trace)

    with authenticated_client(tmp_path, runner) as client:
        response = client.post("/agent/chat", json={"message": "查询任务"})

    assert response.status_code == 200
    assert response.json()["trace"][1]["tool_name"] == "list_tasks"


def test_agent_chat_maps_budget_error_to_429(tmp_path):
    def runner(*args, **kwargs):
        raise AgentBudgetExceededError("Agent Token 预算已超出")

    with authenticated_client(tmp_path, runner) as client:
        response = client.post("/agent/chat", json={"message": "问题"})

    assert response.status_code == 429


def test_agent_chat_maps_knowledge_runtime_failure_to_503(tmp_path):
    def broken_factory():
        raise KnowledgeRuntimeError("embedding 维度不匹配")

    url = f"sqlite+pysqlite:///{(tmp_path / 'agent-rag-error.db').as_posix()}"
    upgrade_database(url)
    app = create_app(
        url,
        token_secret="test-secret-key-at-least-32-bytes",
        agent_runner=lambda *args, **kwargs: None,
        settings_factory=lambda: object(),
        knowledge_executor_factory=broken_factory,
    )
    with TestClient(app) as client:
        client.post("/auth/register", json={
            "username": "alice", "password": "password-123",
        })
        token = client.post("/auth/login", data={
            "username": "alice", "password": "password-123",
        }).json()["access_token"]
        response = client.post(
            "/agent/chat",
            json={"message": "问题"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 503
    assert "维度" in response.json()["detail"]
