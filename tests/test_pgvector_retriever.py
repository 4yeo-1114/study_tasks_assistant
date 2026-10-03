from dataclasses import dataclass

import pytest

from embedding_retrieval import VectorSearchResult
from pgvector_store import PgVectorRetriever
from rag import DocumentChunk


class FakeModel:
    model_name = "test-model"

    def encode(self, text: str):
        assert text == "任务提案怎么确认？"
        return [0.1, 0.2]


class FakeStore:
    def __init__(self):
        self.calls = []

    def search(self, session, *, owner_id, query_vector, limit, source=None, document_version=None):
        self.calls.append((session, owner_id, tuple(query_vector), limit, source, document_version))
        return [
            VectorSearchResult(DocumentChunk("a.md", 1, "确认提案"), 0.9),
            VectorSearchResult(DocumentChunk("b.md", 1, "其他资料"), 0.2),
        ]


class FakeSessionFactory:
    def __call__(self):
        return self

    def __enter__(self):
        return "session"

    def __exit__(self, *args):
        return False


def test_pgvector_retriever_encodes_query_filters_owner_and_score():
    store = FakeStore()
    retriever = PgVectorRetriever(FakeSessionFactory(), FakeModel(), store)

    results = retriever.search(
        "任务提案怎么确认？", owner_id=7, limit=3, min_score=0.5
    )

    assert [(item.chunk.source, item.score) for item in results] == [("a.md", 0.9)]
    assert store.calls == [("session", 7, (0.1, 0.2), 3, None, None)]


def test_pgvector_retriever_forwards_metadata_filters():
    store = FakeStore()
    retriever = PgVectorRetriever(FakeSessionFactory(), FakeModel(), store)

    retriever.search(
        "任务提案怎么确认？",
        owner_id=7,
        source="auth.md",
        document_version="v2",
    )

    assert store.calls[-1][-2:] == ("auth.md", "v2")


def test_pgvector_retriever_rejects_invalid_query_options():
    retriever = PgVectorRetriever(FakeSessionFactory(), FakeModel(), FakeStore())

    with pytest.raises(ValueError, match="问题不能为空"):
        retriever.search("  ", owner_id=7)
    with pytest.raises(ValueError, match="limit"):
        retriever.search("问题", owner_id=7, limit=0)
    with pytest.raises(ValueError, match="min_score"):
        retriever.search("问题", owner_id=7, min_score=1.1)
    with pytest.raises(ValueError, match="source"):
        retriever.search("问题", owner_id=7, source=" ")
    with pytest.raises(ValueError, match="document_version"):
        retriever.search("问题", owner_id=7, document_version=" ")
