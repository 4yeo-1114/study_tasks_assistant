from rag import DocumentChunk, KeywordRetriever, SearchResult
import httpx

from embedding_retrieval import VectorSearchResult
from deepseek_api import DeepSeekSettings
from rag_grounding import (
    GroundedAnswer,
    answer_with_evidence,
    generate_grounded_answer_from_retriever,
)


CHUNKS = [
    DocumentChunk("proposal.md", 2, "confirm 使用 proposal_id 防止重复创建任务"),
    DocumentChunk("auth.md", 1, "JWT 用于认证用户身份"),
]


def test_no_evidence_returns_safe_answer_without_calling_generator():
    called = False

    def generator(context: str) -> str:
        nonlocal called
        called = True
        return "模型编造的答案"

    answer = answer_with_evidence([], generator)

    assert answer.supported is False
    assert "没有找到" in answer.text
    assert called is False


def test_grounded_answer_requires_citation_from_retrieved_sources():
    results = KeywordRetriever(CHUNKS).search("proposal_id 重复创建任务")

    grounded = answer_with_evidence(
        results,
        lambda context: "可以使用 proposal_id 防止重复创建任务。\n[来源: proposal.md#2]",
    )
    unsupported = answer_with_evidence(
        results,
        lambda context: "可以直接重复创建任务。",
    )

    assert grounded == GroundedAnswer(
        "可以使用 proposal_id 防止重复创建任务。\n[来源: proposal.md#2]",
        True,
        ("proposal.md#2",),
    )
    assert unsupported.supported is False
    assert unsupported.citations == ()


def test_fake_or_unretrieved_citation_is_rejected():
    result = SearchResult(CHUNKS[0], score=2)

    answer = answer_with_evidence(
        [result],
        lambda context: "答案\n[来源: other.md#99]",
    )

    assert answer.supported is False
    assert answer.citations == ("other.md#99",)


class RecordingRetriever:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def search(self, query, *, owner_id, limit, min_score):
        self.calls.append((query, owner_id, limit, min_score))
        return self.results


def test_database_retriever_is_connected_to_grounding_and_keeps_owner_id():
    results = [
        VectorSearchResult(CHUNKS[0], 0.91),
    ]
    retriever = RecordingRetriever(results)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "deepseek-flash",
                "choices": [{
                    "message": {
                        "content": "需要确认提案。\n[来源: proposal.md#2]",
                    },
                }],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
            request=request,
        )

    answer = generate_grounded_answer_from_retriever(
        "如何确认提案？",
        retriever,
        owner_id=7,
        settings=DeepSeekSettings("key", "https://example.test", "deepseek-flash"),
        transport=httpx.MockTransport(handler),
    )

    assert answer.supported is True
    assert retriever.calls == [("如何确认提案？", 7, 3, -1.0)]


def test_database_retriever_with_no_results_does_not_call_model():
    retriever = RecordingRetriever([])

    def fail_if_called(request: httpx.Request) -> httpx.Response:
        raise AssertionError("无证据时不应请求模型")

    answer = generate_grounded_answer_from_retriever(
        "没有依据的问题",
        retriever,
        owner_id=7,
        settings=DeepSeekSettings("key", "https://example.test", "deepseek-flash"),
        transport=httpx.MockTransport(fail_if_called),
    )

    assert answer.supported is False
    assert "没有找到" in answer.text
