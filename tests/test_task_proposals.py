import json

import httpx
import pytest

from web.auth import AuthService
from storage.database import Database
from llm.deepseek_api import DeepSeekSettings
from llm.deepseek_tools import ToolCallProposal
from storage.migration import upgrade_database
from tasks.repository import TaskRepository
from tasks.task_proposals import (
    ProposalConflictError,
    ProposalExpiredError,
    ProposalNotFoundError,
    TaskProposalService,
    propose_task_from_model,
)


@pytest.fixture
def setup(tmp_path):
    url = f"sqlite+pysqlite:///{(tmp_path / 'proposals.db').as_posix()}"
    upgrade_database(url)
    database = Database(url)
    auth = AuthService(database.sessions, "test-secret-key-at-least-32-bytes")
    alice = auth.register("alice", "password-123")
    bob = auth.register("bob", "password-123")
    assert alice and bob
    try:
        yield database, alice["id"], bob["id"]
    finally:
        database.dispose()


def call(arguments=None):
    return ToolCallProposal("model-call-1", "create_task", arguments or {
        "title": "  学习 Agent  ", "priority": "high", "due_date": "2026-10-01"
    })


def test_proposal_does_not_write_until_confirmed_and_repeat_is_idempotent(setup):
    database, alice, _ = setup
    service = TaskProposalService(database.sessions, clock=lambda: 1000)
    proposal = service.propose_from_call(alice, call())
    assert proposal["title"] == "学习 Agent"
    assert proposal["status"] == "pending"
    assert proposal["expires_at"] == 1900
    assert TaskRepository(database.sessions).list_tasks(alice) == []

    first = service.confirm(alice, proposal["id"])
    second = service.confirm(alice, proposal["id"])
    assert first == second
    assert first["status"] == "confirmed"
    assert first["task"]["title"] == "学习 Agent"
    assert len(TaskRepository(database.sessions).list_tasks(alice)) == 1


def test_other_user_cannot_read_confirm_or_reject_proposal(setup):
    database, alice, bob = setup
    service = TaskProposalService(database.sessions, clock=lambda: 1000)
    proposal = service.propose_from_call(alice, call())
    with pytest.raises(ProposalNotFoundError):
        service.get(bob, proposal["id"])
    with pytest.raises(ProposalNotFoundError):
        service.confirm(bob, proposal["id"])
    with pytest.raises(ProposalNotFoundError):
        service.reject(bob, proposal["id"])
    assert TaskRepository(database.sessions).list_tasks(alice) == []


def test_reconfirm_after_task_was_deleted_never_creates_again(setup):
    database, alice, _ = setup
    service = TaskProposalService(database.sessions, clock=lambda: 1000)
    proposal = service.propose_from_call(alice, call())
    created = service.confirm(alice, proposal["id"])
    task_id = created["task"]["id"]
    assert TaskRepository(database.sessions).delete_task(alice, task_id)
    repeated = service.confirm(alice, proposal["id"])
    assert repeated["task_id"] == task_id
    assert repeated["task"] is None
    assert TaskRepository(database.sessions).list_tasks(alice) == []


def test_rejected_and_expired_proposals_never_write(setup):
    database, alice, _ = setup
    now = [1000]
    service = TaskProposalService(database.sessions, clock=lambda: now[0])
    rejected = service.propose_from_call(alice, call())
    assert service.reject(alice, rejected["id"])["status"] == "rejected"
    with pytest.raises(ProposalConflictError):
        service.confirm(alice, rejected["id"])
    expired = service.propose_from_call(alice, call(), ttl_seconds=10)
    now[0] = 1010
    with pytest.raises(ProposalExpiredError):
        service.confirm(alice, expired["id"])
    assert TaskRepository(database.sessions).list_tasks(alice) == []


@pytest.mark.parametrize("arguments", [
    {"title": " "},
    {"title": "x", "priority": "urgent"},
    {"title": "x", "owner_id": 999},
    {"title": "x", "user_id": 999},
])
def test_invalid_model_arguments_cannot_create_proposal(setup, arguments):
    database, alice, _ = setup
    service = TaskProposalService(database.sessions)
    with pytest.raises(ValueError):
        service.propose_from_call(alice, call(arguments))
    assert TaskRepository(database.sessions).list_tasks(alice) == []


def test_model_only_proposes_and_cannot_execute_or_choose_owner(setup):
    database, alice, bob = setup
    service = TaskProposalService(database.sessions, clock=lambda: 1000)
    settings = DeepSeekSettings("test-key", "https://api.deepseek.example", "deepseek-flash")

    def handler(request):
        body = json.loads(request.content)
        assert body["tools"][0]["function"]["name"] == "create_task"
        return httpx.Response(200, json={
            "model": "deepseek-flash",
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            "choices": [{"finish_reason": "tool_calls", "message": {
                "tool_calls": [{"id": "call-1", "type": "function", "function": {
                    "name": "create_task", "arguments": json.dumps({
                        "title": "复习 SQL", "priority": "low"
                    })}}]
            }}],
        })

    proposal = propose_task_from_model("帮我记一条任务", user_id=alice, service=service,
                                       settings=settings, transport=httpx.MockTransport(handler))
    assert proposal["title"] == "复习 SQL"
    assert TaskRepository(database.sessions).list_tasks(alice) == []
    assert TaskRepository(database.sessions).list_tasks(bob) == []
    service.confirm(alice, proposal["id"])
    assert len(TaskRepository(database.sessions).list_tasks(alice)) == 1
    assert TaskRepository(database.sessions).list_tasks(bob) == []


def test_same_owner_and_idempotency_key_reuses_proposal(setup):
    database, alice, _ = setup
    service = TaskProposalService(database.sessions, clock=lambda: 1000)

    first = service.propose_from_call(
        alice, call(), idempotency_key="agent-run-1:create-task"
    )
    second = service.propose_from_call(
        alice, call(), idempotency_key="agent-run-1:create-task"
    )

    assert first == second


def test_same_idempotency_key_with_different_arguments_is_rejected(setup):
    database, alice, _ = setup
    service = TaskProposalService(database.sessions, clock=lambda: 1000)
    service.propose_from_call(
        alice, call(), idempotency_key="agent-run-1:create-task"
    )

    with pytest.raises(ProposalConflictError, match="幂等键"):
        service.propose_from_call(
            alice,
            call({"title": "不同任务"}),
            idempotency_key="agent-run-1:create-task",
        )
