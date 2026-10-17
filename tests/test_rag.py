import pytest

from knowledge.rag import DocumentChunk, KeywordRetriever, tokenize, build_context


def test_tokenize_keeps_chinese_terms_and_english_words():
    assert tokenize("确认 proposal 是否重复") == {
        "确认",
        "proposal",
        "是否",
        "重复",
    }


def test_retriever_ranks_matching_chunks_and_keeps_sources():
    retriever = KeywordRetriever([
        DocumentChunk("notes/auth.md", 1, "JWT 用于认证用户身份"),
        DocumentChunk("notes/proposal.md", 2, "confirm 使用 proposal_id 防止重复创建任务"),
        DocumentChunk("notes/sql.md", 3, "SELECT 查询数据库记录"),
    ])

    results = retriever.search("proposal_id 重复创建任务", limit=2)

    assert [item.chunk.source for item in results] == ["notes/proposal.md"]
    assert results[0].score >= 3


def test_retriever_returns_no_results_when_no_terms_match():
    retriever = KeywordRetriever([
        DocumentChunk("notes/auth.md", 1, "JWT 用于认证用户身份"),
    ])

    assert retriever.search("向量数据库", limit=3) == []


def test_search_rejects_invalid_limit_and_empty_query():
    retriever = KeywordRetriever([])

    with pytest.raises(ValueError, match="问题不能为空"):
        retriever.search("  ")
    with pytest.raises(ValueError, match="limit"):
        retriever.search("任务", limit=0)


def test_build_context_includes_ranked_text_and_source_or_no_evidence():
    chunk = DocumentChunk("notes/rag.md", 4, "检索结果必须保留来源")

    assert "[来源: notes/rag.md#4]" in build_context([chunk])
    assert "没有找到" in build_context([])


def test_min_score_filters_low_relevance_chunks():
    retriever = KeywordRetriever([
        DocumentChunk("notes/weak.md", 1, "任务需要记录"),
        DocumentChunk("notes/strong.md", 2, "任务需要记录任务状态和任务优先级"),
    ])

    results = retriever.search("任务 状态 优先级", min_score=2)

    assert [item.chunk.source for item in results] == ["notes/strong.md"]
