import json

from retrieval_eval import (
    RetrievalTelemetry,
    evaluate_searcher_with_telemetry,
    report_to_json,
    report_to_markdown,
)
from rag import DocumentChunk, SearchResult


def searcher(query, limit):
    if "无" in query:
        return []
    return [SearchResult(DocumentChunk("guide.md", 1, "证据"), 0.9)][:limit]


def test_evaluation_records_candidates_and_latency():
    report = evaluate_searcher_with_telemetry(
        searcher,
        [
            {"name": "命中", "query": "怎么做", "expected_sources": ("guide.md",)},
            {"name": "无资料", "query": "无资料", "expected_sources": (), "expected_empty": True},
        ],
        limit=1,
    )
    assert report.total == 2
    assert all(item.elapsed_ms >= 0 for item in report.telemetry)
    assert report.telemetry[0].candidate_count == 1
    assert report.telemetry[1].candidate_count == 0


def test_reports_are_machine_and_human_readable():
    report = evaluate_searcher_with_telemetry(
        searcher,
        [{"name": "命中", "query": "怎么做", "expected_sources": ("guide.md",)}],
    )
    payload = json.loads(report_to_json(report))
    assert payload["total"] == 1
    markdown = report_to_markdown(report)
    assert "命中" in markdown
    assert "elapsed_ms" in markdown
