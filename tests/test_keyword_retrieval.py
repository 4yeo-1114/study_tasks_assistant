import pytest

from knowledge.hybrid_retrieval import HybridRetriever, RetrievalFilters
from knowledge.keyword_retrieval import KeywordIndexedChunk, ScopedKeywordRetriever
from knowledge.rag import DocumentChunk


def record(owner_id, version, source, chunk_id, text):
    return KeywordIndexedChunk(
        owner_id=owner_id,
        document_version=version,
        chunk=DocumentChunk(source, chunk_id, text),
    )


def test_scoped_keyword_retriever_filters_owner_source_and_version_before_scoring():
    retriever = ScopedKeywordRetriever([
        record(1, "v1", "auth.md", 1, "JWT user_id 认证"),
        record(2, "v1", "auth.md", 1, "JWT user_id 认证"),
        record(1, "v2", "auth.md", 1, "JWT user_id 认证"),
        record(1, "v1", "tasks.md", 1, "JWT user_id 认证"),
    ])

    results = retriever.search(
        "JWT user_id",
        owner_id=1,
        source="auth.md",
        document_version="v1",
    )

    assert [(item.chunk.source, item.chunk.chunk_id) for item in results] == [("auth.md", 1)]


def test_hybrid_retriever_accepts_scoped_keyword_adapter():
    keyword = ScopedKeywordRetriever([
        record(1, "v1", "auth.md", 1, "JWT user_id 认证"),
    ])
    vector = ScopedKeywordRetriever([
        record(1, "v1", "auth.md", 1, "JWT user_id 认证"),
    ])

    results = HybridRetriever(keyword, vector).search(
        "JWT user_id",
        filters=RetrievalFilters(owner_id=1, document_version="v1"),
    )

    assert len(results) == 1
    assert results[0].chunk.source == "auth.md"


def test_scoped_keyword_retriever_rejects_invalid_scope():
    retriever = ScopedKeywordRetriever([])

    with pytest.raises(ValueError, match="owner_id"):
        retriever.search("问题", owner_id=0)
    with pytest.raises(ValueError, match="source"):
        retriever.search("问题", owner_id=1, source=" ")
    with pytest.raises(ValueError, match="document_version"):
        retriever.search("问题", owner_id=1, document_version=" ")
