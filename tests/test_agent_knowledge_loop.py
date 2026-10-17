import json

import httpx

from agent.agent_loop import run_readonly_agent
from llm.deepseek_api import DeepSeekSettings
from knowledge.hybrid_retrieval import RetrievalCandidate
from knowledge.rag import DocumentChunk
from agent.knowledge_tools import KnowledgeToolExecutor


SETTINGS = DeepSeekSettings("test-key", "https://api.deepseek.example", "deepseek-flash")


class FakeRetriever:
    def __init__(self):
        self.calls = []

    def search(self, query, *, limit, filters):
        self.calls.append((query, limit, filters))
        return [
            RetrievalCandidate(
                chunk=DocumentChunk("auth.md", 1, "JWT 的 sub 标识用户。"),
                fused_score=0.8,
                keyword_rank=1,
                vector_rank=1,
                keyword_score=0.9,
                vector_score=0.8,
            )
        ]


def test_agent_executes_knowledge_tool_and_returns_matching_tool_message():
    requests = []
    retriever = FakeRetriever()
    executor = KnowledgeToolExecutor(retriever)

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            assert body["messages"][0]["role"] == "system"
            assert "search_knowledge" in body["messages"][0]["content"]
            return httpx.Response(200, json={
                "choices": [{"finish_reason": "tool_calls", "message": {
                    "role": "assistant", "content": None, "tool_calls": [{
                        "id": "call-k", "type": "function",
                        "function": {"name": "search_knowledge", "arguments": json.dumps({"query": "JWT"})},
                    }],
                }}]
            })
        assert body["messages"][2]["tool_calls"][0]["id"] == "call-k"
        assert body["messages"][3]["role"] == "tool"
        assert body["messages"][3]["tool_call_id"] == "call-k"
        assert json.loads(body["messages"][3]["content"])[0]["source"] == "auth.md"
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {
                "role": "assistant", "content": "JWT 的 sub 标识用户。[来源: auth.md#1]",
            }}]
        })

    result = run_readonly_agent(
        "JWT 如何识别用户？",
        user_id=7,
        service=object(),
        settings=SETTINGS,
        knowledge_executor=executor,
        transport=httpx.MockTransport(handler),
    )

    assert result.answer.endswith("auth.md#1]")
    assert retriever.calls[0][2].owner_id == 7
