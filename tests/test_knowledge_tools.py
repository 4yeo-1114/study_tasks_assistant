import json
import logging

import pytest

from llm.deepseek_tools import ToolCallProposal
from agent.knowledge_tools import (
    SEARCH_KNOWLEDGE_TOOL,
    KnowledgeToolExecutor,
    SearchKnowledgeArguments,
)
from core.observability import request_context


class FakeRetriever:
    def __init__(self):
        self.calls = []

    def search(self, query, *, limit, filters):
        self.calls.append((query, limit, filters))
        return []


def test_schema_exposes_only_query_and_limit():
    parameters = SEARCH_KNOWLEDGE_TOOL["function"]["parameters"]
    assert set(parameters["properties"]) == {"query", "limit"}
    assert "owner_id" not in parameters["properties"]


def test_arguments_validate_bounds_and_extra_fields():
    assert SearchKnowledgeArguments(query="JWT", limit=2).limit == 2
    with pytest.raises(ValueError):
        SearchKnowledgeArguments(query="", limit=2)
    with pytest.raises(ValueError):
        SearchKnowledgeArguments(query="JWT", limit=6)


def test_executor_injects_owner_and_preserves_call_id():
    retriever = FakeRetriever()
    executor = KnowledgeToolExecutor(retriever)
    result = executor.execute(
        ToolCallProposal("call-k", "search_knowledge", {"query": "JWT"}),
        owner_id=7,
    )
    assert result.call_id == "call-k"
    assert retriever.calls[0][2].owner_id == 7
    assert result.output == [{"found": False, "message": "没有找到与问题直接相关的资料。"}]


def test_executor_limits_repeated_calls():
    executor = KnowledgeToolExecutor(FakeRetriever(), max_calls=1)
    call = ToolCallProposal("call-1", "search_knowledge", {"query": "JWT"})
    executor.execute(call, owner_id=1)
    with pytest.raises(ValueError, match="次数"):
        executor.execute(
            ToolCallProposal("call-2", "search_knowledge", {"query": "RAG"}),
            owner_id=1,
        )


def test_executor_logs_cache_and_candidate_metadata_without_query(caplog):
    executor = KnowledgeToolExecutor(FakeRetriever())
    query = "private retrieval query"

    with request_context("http-1"):
        with caplog.at_level(logging.INFO, logger="study_task.knowledge"):
            executor.execute(
                ToolCallProposal("call-1", "search_knowledge", {"query": query}),
                owner_id=1,
            )
            executor.execute(
                ToolCallProposal("call-2", "search_knowledge", {"query": query}),
                owner_id=1,
            )

    events = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "study_task.knowledge"
    ]
    assert [event["cache_hit"] for event in events] == [False, True]
    assert [event["candidate_count"] for event in events] == [0, 0]
    assert all(event["request_id"] == "http-1" for event in events)
    assert all(event["duration_ms"] >= 0 for event in events)
    assert query not in caplog.text
