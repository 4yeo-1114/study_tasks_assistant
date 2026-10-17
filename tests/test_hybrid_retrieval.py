from dataclasses import dataclass

from knowledge.rag import DocumentChunk
from knowledge.hybrid_retrieval import HybridRetriever


@dataclass(frozen=True)
class FakeResult:
    chunk: DocumentChunk
    score: float


class FakeRetriever:
    def __init__(self, results_by_query):
        self.results_by_query = results_by_query
        self.calls = []

    def search(self, query: str, *, limit: int = 3):
        self.calls.append(limit)
        return list(self.results_by_query.get(query, ()))[:limit]


def chunk(source: str, chunk_id: int) -> DocumentChunk:
    return DocumentChunk(source, chunk_id, f"{source}-{chunk_id}")


def test_hybrid_retriever_oversamples_before_final_cutoff():
    keyword_results = [FakeResult(chunk("keyword.md", i), 1.0) for i in range(1, 6)]
    vector_results = [FakeResult(chunk("vector.md", i), 1.0) for i in range(1, 6)]
    keyword = FakeRetriever({"q": keyword_results})
    vector = FakeRetriever({"q": vector_results})

    results = HybridRetriever(keyword, vector).search("q", limit=3, candidate_limit=5)

    assert keyword.calls == [5]
    assert vector.calls == [5]
    assert len(results) == 3


def test_hybrid_retriever_deduplicates_and_fuses_ranks():
    shared = chunk("guide.md", 1)
    keyword_only = chunk("terms.md", 2)
    vector_only = chunk("faq.md", 3)
    keyword = FakeRetriever({"q": [FakeResult(shared, 5), FakeResult(keyword_only, 4)]})
    vector = FakeRetriever({"q": [FakeResult(shared, 0.9), FakeResult(vector_only, 0.8)]})

    results = HybridRetriever(keyword, vector).search("q", limit=3)

    keys = {(item.chunk.source, item.chunk.chunk_id) for item in results}
    assert keys == {("guide.md", 1), ("terms.md", 2), ("faq.md", 3)}
    assert results[0].chunk.source == "guide.md"
    assert results[0].keyword_rank == 1
    assert results[0].vector_rank == 1
    assert results[0].fused_score > results[1].fused_score
    assert len(results) == 3


def test_hybrid_retriever_keeps_results_when_one_side_is_empty():
    keyword = FakeRetriever({"q": []})
    vector = FakeRetriever({"q": [FakeResult(chunk("faq.md", 1), 0.8)]})

    results = HybridRetriever(keyword, vector).search("q", limit=3)

    assert len(results) == 1
    assert results[0].keyword_rank is None
    assert results[0].vector_rank == 1


def test_hybrid_retriever_rejects_invalid_arguments():
    retriever = HybridRetriever(FakeRetriever({}), FakeRetriever({}))

    try:
        retriever.search("q", limit=0)
    except ValueError as exc:
        assert "limit" in str(exc)
    else:
        raise AssertionError("limit=0 should fail")
from dataclasses import dataclass

import pytest

from knowledge.hybrid_retrieval import HybridRetriever, RetrievalFilters
from knowledge.rag import DocumentChunk


@dataclass(frozen=True)
class Result:
    chunk: DocumentChunk
    score: float


class FilterAwareRetriever:
    def __init__(self):
        self.filters = []

    def search(self, query, *, limit=3, owner_id, source=None, document_version=None):
        self.filters.append((owner_id, source, document_version))
        return [Result(DocumentChunk("a.md", 1, "资料"), 0.9)]


def test_hybrid_retriever_forwards_one_filter_contract_to_both_sides():
    keyword = FilterAwareRetriever()
    vector = FilterAwareRetriever()
    retriever = HybridRetriever(keyword, vector)

    retriever.search(
        "问题",
        filters=RetrievalFilters(owner_id=7, source="a.md", document_version="v2"),
    )

    assert keyword.filters == [(7, "a.md", "v2")]
    assert vector.filters == [(7, "a.md", "v2")]


def test_hybrid_retriever_rejects_unscoped_side_when_filters_are_required():
    class UnscopedRetriever:
        def search(self, query, *, limit=3):
            return []

    retriever = HybridRetriever(UnscopedRetriever(), FilterAwareRetriever())

    with pytest.raises(TypeError, match="owner_id"):
        retriever.search("问题", filters=RetrievalFilters(owner_id=7))
