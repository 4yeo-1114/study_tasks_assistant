import importlib
import json
from types import SimpleNamespace

import pytest

from knowledge.rag import DocumentChunk


def baseline():
    return importlib.import_module("knowledge.retrieval_baseline")


def test_threshold_summary_separates_answered_recall_and_no_answer_accuracy():
    from scripts.run_pg_vector_threshold_eval import summarize_threshold_rows

    rows = [
        {"threshold": 0.5, "recall_at_5": 1.0, "no_answer_correct": None},
        {"threshold": 0.5, "recall_at_5": None, "no_answer_correct": True},
        {"threshold": 0.8, "recall_at_5": 0.0, "no_answer_correct": None},
        {"threshold": 0.8, "recall_at_5": None, "no_answer_correct": True},
    ]
    summary = summarize_threshold_rows(rows)
    assert summary["0.5"]["mean_recall_at_5"] == 1.0
    assert summary["0.5"]["no_answer_accuracy"] == 1.0
    assert summary["0.8"]["mean_recall_at_5"] == 0.0


class ScopedRetriever:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def search(self, query, *, owner_id, limit, source=None, document_version=None):
        self.calls.append((query, owner_id, limit, source, document_version))
        return self.result


class HybridRetriever:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def search(self, query, *, limit, filters):
        self.calls.append((query, limit, filters))
        return self.result


def test_scoped_baseline_invokes_all_strategies_with_same_owner_and_limit():
    chunk = DocumentChunk("note.md", 1, "JWT")
    result = [SimpleNamespace(chunk=chunk)]
    keyword = ScopedRetriever(result)
    vector = ScopedRetriever(result)
    hybrid = HybridRetriever(result)
    cases = [{"id": "q1", "query": "JWT", "split": "development", "relevant_chunks": ["note.md#1"]}]

    rows = baseline().run_scoped(
        cases, {"keyword": keyword, "vector": vector, "hybrid": hybrid},
        owner_id=7, k=5, rounds=2, warmups=1,
    )

    assert len(rows) == 6
    assert {row["strategy"] for row in rows} == {"keyword", "vector", "hybrid"}
    assert all(row["actual_chunks"] == ["note.md#1"] for row in rows)
    assert all(row["elapsed_ms"] >= 0 for row in rows)
    assert keyword.calls == [("JWT", 7, 5, None, None)] * 3
    assert vector.calls == [("JWT", 7, 5, None, None)] * 3
    assert len(hybrid.calls) == 3
    assert all(call[2].owner_id == 7 for call in hybrid.calls)


def test_scoped_baseline_rejects_invalid_owner_before_calls():
    retriever = ScopedRetriever([])
    with pytest.raises(ValueError, match="owner_id"):
        baseline().run_scoped(
            [{"id": "q", "query": "JWT", "split": "development", "relevant_chunks": []}],
            {"keyword": retriever}, owner_id=0,
        )
    assert retriever.calls == []


def test_case_file_rejects_unknown_and_inactive_labels(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({
        "version": "dev-v1",
        "cases": [{"id": "q1", "query": "JWT", "split": "development", "relevant_chunks": ["old.md#1"]}],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown"):
        baseline().load_cases(path, {"active.md#1"})


def test_case_file_accepts_active_labels_and_no_answer(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({
        "version": "dev-v1", "cases": [
            {"id": "q1", "query": "JWT", "split": "development", "relevant_chunks": ["active.md#1"]},
            {"id": "q2", "query": "未知主题", "split": "frozen", "relevant_chunks": []},
        ],
    }), encoding="utf-8")
    cases = baseline().load_cases(path, {"active.md#1"})
    assert len(cases) == 2
    assert cases[1]["relevant_chunks"] == []


def test_case_file_allows_smoke_only_when_explicit(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"cases": [
        {"id": "s1", "query": "JWT", "split": "smoke", "relevant_chunks": ["active.md#1"]}
    ]}), encoding="utf-8")
    with pytest.raises(ValueError, match="split"):
        baseline().load_cases(path, {"active.md#1"})
    assert baseline().load_cases(path, {"active.md#1"}, allow_smoke=True)[0]["split"] == "smoke"


def test_case_file_rejects_ai_candidate_without_explicit_opt_in(tmp_path):
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps({"dataset_kind": "ai_generated_candidate", "cases": [
        {"id": "q1", "query": "JWT", "split": "development", "relevant_chunks": ["active.md#1"]}
    ]}), encoding="utf-8")
    with pytest.raises(ValueError, match="allow_candidate"):
        baseline().load_cases(path, {"active.md#1"})
    assert baseline().load_cases(path, {"active.md#1"}, allow_candidate=True)[0]["id"] == "q1"


def test_summary_by_strategy_preserves_independent_denominators():
    module = baseline()
    rows = [
        {"strategy": "keyword", "elapsed_ms": 5, **module.score_ranking(["a#1"], ["a#1"], k=5)},
        {"strategy": "keyword", "elapsed_ms": 6, **module.score_ranking([], [], k=5)},
        {"strategy": "vector", "elapsed_ms": 10, **module.score_ranking([], ["a#1"], k=5)},
        {"strategy": "vector", "elapsed_ms": 12, **module.score_ranking(["x#1"], [], k=5)},
    ]
    summary = module.summarize_strategies(rows)
    assert summary["keyword"]["mean_recall_at_k"] == 1
    assert summary["keyword"]["no_answer_accuracy"] == 1
    assert summary["vector"]["mean_recall_at_k"] == 0
    assert summary["vector"]["no_answer_accuracy"] == 0


def test_summary_by_split_does_not_mix_development_and_frozen():
    module = baseline()
    rows = [
        {"strategy": "keyword", "split": "development", "case_id": "d1", "elapsed_ms": 1,
         **module.score_ranking(["a#1"], ["a#1"], k=5)},
        {"strategy": "keyword", "split": "frozen", "case_id": "f1", "elapsed_ms": 2,
         **module.score_ranking([], ["b#1"], k=5)},
    ]
    result = module.summarize_by_split(rows)
    assert result["development"]["keyword"]["mean_recall_at_k"] == 1
    assert result["frozen"]["keyword"]["mean_recall_at_k"] == 0
    assert result["development"]["keyword"]["unique_queries"] == 1


def test_active_chunk_query_limits_owner_ready_and_active_version():
    captured = {}

    class Session:
        def execute(self, statement, params):
            captured["sql"] = str(statement)
            captured["params"] = params
            return [SimpleNamespace(source="active.md", chunk_id=1)]

    class Sessions:
        def __call__(self):
            class Context:
                def __enter__(self):
                    return Session()

                def __exit__(self, *args):
                    return False
            return Context()

    assert baseline().active_chunk_ids(Sessions(), owner_id=7) == {"active.md#1"}
    assert captured["params"] == {"owner_id": 7}
    assert "document_chunks.owner_id = :owner_id" in captured["sql"]
    assert "documents.state = 'ready'" in captured["sql"]
    assert "documents.active_version = document_chunks.document_version" in captured["sql"]


def test_experiment_database_guard_rejects_main_database():
    with pytest.raises(ValueError, match="study_tasks_eval"):
        baseline().require_experiment_database("postgresql+psycopg://u:p@localhost/study_tasks")
    baseline().require_experiment_database(
        "postgresql+psycopg://u:p@localhost/study_tasks_eval"
    )
