import pytest

from knowledge.retrieval_scale import (
    bare_vector_sql, build_scale_dataset, deterministic_vector, explain_vector_sql,
    filtered_vector_sql,
    neighbor_overlap, summarize_plan,
)
from knowledge.formal_dataset import build_formal_candidate


BASE = {
    "version": "smoke-v1",
    "chunks": [
        {"source": "a.md", "chunk_id": 1, "text": "anchor"},
        {"source": "b.md", "chunk_id": 1, "text": "anchor two"},
    ],
    "cases": [{"id": "q1", "query": "anchor", "relevant_chunks": ["a.md#1"]}],
}


def test_formal_candidate_has_120_cases_and_explicit_review_status():
    base = {
        "chunks": [
            {"source": source, "chunk_id": int(chunk_id), "text": "fixture"}
            for source, chunk_id in (
                ("auth.md", "1"), ("auth.md", "2"),
                ("proposals.md", "1"), ("proposals.md", "2"),
                ("retrieval.md", "1"), ("retrieval.md", "2"),
                ("ingestion.md", "1"), ("ingestion.md", "2"),
                ("fitness.md", "1"), ("fitness.md", "2"),
            )
        ]
    }
    candidate = build_formal_candidate(base)
    assert candidate["dataset_kind"] == "ai_generated_candidate"
    assert candidate["review_status"] == "pending_human_review"
    assert len(candidate["cases"]) == 120
    assert sum(row["split"] == "development" for row in candidate["cases"]) == 40
    assert sum(row["split"] == "frozen" for row in candidate["cases"]) == 80
    assert sum(row["split"] == "development" and not row["relevant_chunks"]
               for row in candidate["cases"]) == 20
    assert sum(row["split"] == "frozen" and not row["relevant_chunks"]
               for row in candidate["cases"]) == 20
    assert len({row["id"] for row in candidate["cases"]}) == 120


def test_scale_fixture_has_exact_size_and_preserves_labels():
    fixture = build_scale_dataset(BASE, 1000)
    assert len(fixture["chunks"]) == 1000
    assert fixture["target_chunk_count"] == 1000
    assert fixture["cases"][0]["relevant_chunks"] == ["a.md#1"]
    ids = {(row["source"], row["chunk_id"]) for row in fixture["chunks"]}
    assert len(ids) == 1000


def test_scale_fixture_rejects_size_smaller_than_base():
    with pytest.raises(ValueError, match="不能小于"):
        build_scale_dataset(BASE, 1)


def test_explain_sql_distinguishes_exact_and_indexed_modes():
    sql = explain_vector_sql()
    assert "FROM document_chunks" in sql
    assert "JOIN documents" in sql
    assert "document_chunks.owner_id = :owner_id" in sql
    assert "documents.active_version = document_chunks.document_version" in sql
    assert "ORDER BY document_chunks.embedding <=> CAST(:query_vector AS vector)" in sql
    assert "LIMIT :limit" in sql
    assert explain_vector_sql(explain=False).lstrip().startswith("SELECT")


def test_plan_summary_reports_actual_index_usage_and_output_rows():
    plan = [{"Plan": {"Node Type": "Limit", "Actual Rows": 5, "Plans": [
        {"Node Type": "Sort", "Actual Rows": 5, "Plans": [
            {"Node Type": "Bitmap Heap Scan", "Relation Name": "document_chunks",
             "Actual Rows": 1000, "Actual Loops": 1, "Plans": []},
        ]},
    ]}}]
    summary = summarize_plan(plan)
    assert summary["uses_hnsw"] is False
    assert summary["chunk_rows_output"] == 1000


def test_deterministic_probe_vectors_are_distinct_and_repeatable():
    first = deterministic_vector(1, dimension=4)
    assert first == deterministic_vector(1, dimension=4)
    assert first != deterministic_vector(2, dimension=4)
    assert len(first) == 4
    with pytest.raises(ValueError, match="正整数"):
        deterministic_vector(0, dimension=4)


def test_neighbor_overlap_counts_top_k_intersection():
    assert neighbor_overlap(["a#1", "b#1", "c#1"], ["b#1", "c#1", "x#1"], k=3) == 2 / 3
    with pytest.raises(ValueError, match="k"):
        neighbor_overlap([], [], k=0)


def test_bare_probe_sql_keeps_owner_and_embedding_filters_before_limit():
    sql = bare_vector_sql()
    assert "owner_id = :owner_id" in sql
    assert "embedding_model = :embedding_model" in sql
    assert "embedding_dimension = :embedding_dimension" in sql
    assert "ORDER BY embedding <=> CAST(:query_vector AS vector)" in sql
    assert "LIMIT :limit" in sql
    assert bare_vector_sql(explain=True).lstrip().startswith("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)")


def test_filtered_vector_sql_applies_ann_window_before_lifecycle_filter():
    sql = filtered_vector_sql(candidate_limit=25)
    assert "WITH ann_candidates AS" in sql
    assert "LIMIT :candidate_limit" in sql
    assert "documents.active_version = ann_candidates.document_version" in sql
    assert "LIMIT :limit" in sql
    with pytest.raises(ValueError, match="candidate_limit"):
        filtered_vector_sql(candidate_limit=0)
