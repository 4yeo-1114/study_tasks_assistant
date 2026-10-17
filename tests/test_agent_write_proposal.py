import json

import httpx

from agent.agent_loop import AgentState, run_readonly_agent
from web.auth import AuthService
from storage.database import Database
from llm.deepseek_api import DeepSeekSettings
from storage.migration import upgrade_database
from tasks.repository import TaskRepository
from tasks.task_proposals import TaskProposalService


def test_agent_create_task_only_persists_pending_proposal(tmp_path):
    url = f"sqlite+pysqlite:///{(tmp_path / 'write-agent.db').as_posix()}"
    upgrade_database(url)
    database = Database(url)
    try:
        auth = AuthService(database.sessions, "test-secret-key-at-least-32-bytes")
        user = auth.register("writer", "password-123")
        proposals = TaskProposalService(database.sessions, clock=lambda: 1000)
        settings = DeepSeekSettings("key", "https://api.deepseek.example", "model")
        calls = 0

        def handler(request):
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(200, json={"choices": [{
                    "finish_reason": "tool_calls",
                    "message": {"role": "assistant", "content": None, "tool_calls": [{
                        "id": "call-create", "type": "function", "function": {
                            "name": "create_task",
                            "arguments": json.dumps({"title": "复习 Agent", "priority": "high"}),
                        },
                    }]},
                }]})
            return httpx.Response(200, json={"choices": [{
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "提案已创建，等待你的确认。"},
            }]})

        result = run_readonly_agent(
            "创建高优先级任务：复习 Agent",
            user_id=user["id"],
            service=object(),
            proposal_service=proposals,
            settings=settings,
            transport=httpx.MockTransport(handler),
        )

        assert TaskRepository(database.sessions).list_tasks(user["id"]) == []
        proposal_events = [event for event in result.trace if event.proposal_id]
        assert len(proposal_events) == 1
        assert proposal_events[0].state == AgentState.EXECUTING
        assert proposals.get(user["id"], proposal_events[0].proposal_id)["status"] == "pending"
    finally:
        database.dispose()
