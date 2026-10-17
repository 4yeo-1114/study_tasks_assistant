import importlib
import json
import zipfile

import pytest


def baseline():
    # Import inside tests so missing implementation is an explicit RED result.
    return importlib.import_module("knowledge.retrieval_baseline")


def test_recall_counts_chunks_and_duplicate_results_do_not_inflate_it():
    result = baseline().score_ranking(
        ["a#1", "x#1", "b#2", "b#2", "y#1"],
        ["a#1", "b#2", "c#3", "d#4"],
        k=5,
    )
    assert result == {"recall_at_k": 0.5, "reciprocal_rank_at_k": 1.0,
                      "no_answer_correct": None}


def test_rank_three_and_cutoff_use_original_positions():
    result = baseline().score_ranking(["x#1", "y#1", "a#1"], ["a#1"], k=5)
    assert result["reciprocal_rank_at_k"] == pytest.approx(1 / 3)
    assert baseline().score_ranking(["x#1", "a#1"], ["a#1"], k=1)["recall_at_k"] == 0
    assert baseline().score_ranking(["x#1", "x#1", "a#1"], ["a#1"], k=5)["reciprocal_rank_at_k"] == pytest.approx(1 / 3)


def test_no_answer_is_excluded_from_recall_and_mrr():
    module = baseline()
    assert module.score_ranking([], [], k=5)["no_answer_correct"] is True
    assert module.score_ranking(["x#1"], [], k=5)["no_answer_correct"] is False
    report = module.summarize([
        {**module.score_ranking(["a#1"], ["a#1"], k=5), "elapsed_ms": 10},
        {**module.score_ranking([], [], k=5), "elapsed_ms": 20},
    ])
    assert report["mean_recall_at_k"] == 1
    assert report["mrr_at_k"] == 1
    assert report["no_answer_accuracy"] == 1
    assert report["p50_ms"] == 15
    assert report["p95_ms"] == pytest.approx(19.5)


def test_dataset_rejects_unknown_labels_and_duplicate_ids(tmp_path):
    module = baseline()
    data = {"dataset_kind": "synthetic_smoke", "chunks": [
        {"source": "a.md", "chunk_id": 1, "text": "JWT"}], "cases": [
        {"id": "q1", "query": "JWT", "split": "smoke", "relevant_chunks": ["missing#1"]}]}
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown"):
        module.load_dataset(path)
    data["cases"][0]["relevant_chunks"] = ["a.md#1"]
    data["cases"].append(data["cases"][0].copy())
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        module.load_dataset(path)


@pytest.mark.parametrize("change", ["blank_query", "empty_cases", "string_labels", "invalid_split"])
def test_dataset_rejects_invalid_experiment_inputs(tmp_path, change):
    data = {"chunks": [{"source": "a.md", "chunk_id": 1, "text": "JWT"}],
            "cases": [{"id": "q1", "query": "JWT", "split": "smoke", "relevant_chunks": ["a.md#1"]}]}
    if change == "blank_query":
        data["cases"][0]["query"] = " "
    elif change == "empty_cases":
        data["cases"] = []
    elif change == "string_labels":
        data["cases"][0]["relevant_chunks"] = "a.md#1"
    else:
        data["cases"][0]["split"] = "anything"
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        baseline().load_dataset(path)


def test_snapshot_includes_untracked_source_and_excludes_runtime_secrets(tmp_path):
    module = baseline()
    root = tmp_path / "repo"
    app = root / "study_task_assistant"
    app.mkdir(parents=True)
    (app / "new.py").write_text("VALUE = 1\n", encoding="utf-8")
    (app / ".env").write_text("SECRET=never-copy", encoding="utf-8")
    (app / "tasks.json").write_text("private", encoding="utf-8")
    (app / "tasks.db").write_bytes(b"private")
    cache = app / "__pycache__"
    cache.mkdir()
    (cache / "secret.py").write_text("private", encoding="utf-8")
    output = tmp_path / "snapshot"
    manifest = module.snapshot_source(root, output)
    with zipfile.ZipFile(output / "source.zip") as archive:
        assert archive.namelist() == ["study_task_assistant/new.py"]
        assert archive.read(archive.namelist()[0]) == (app / "new.py").read_bytes()
    first_hash = manifest["source_sha256"]
    (app / "new.py").write_text("VALUE = 2\n", encoding="utf-8")
    second = module.snapshot_source(root, tmp_path / "second")
    assert first_hash != second["source_sha256"]


def test_snapshot_is_stable_and_excludes_unrelated_and_unknown_files(tmp_path):
    root = tmp_path / "repo"
    app = root / "study_task_assistant"
    app.mkdir(parents=True)
    (app / "main.py").write_bytes(b"x = 1\n")
    (app / "key.pem").write_text("private", encoding="utf-8")
    (app / "notes.json").write_text("private", encoding="utf-8")
    (root / "private.md").write_text("private", encoding="utf-8")
    first = baseline().snapshot_source(root, root / "runs" / "one")
    second = baseline().snapshot_source(root, root / "runs" / "two")
    assert first["source_sha256"] == second["source_sha256"]
    assert first["file_count"] == 1


def test_snapshot_includes_runner_and_fixture_with_source(tmp_path):
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "benchmarks").mkdir()
    (root / "scripts" / "run.py").write_text("print('run')", encoding="utf-8")
    (root / "benchmarks" / "retrieval_smoke.json").write_text("{}", encoding="utf-8")
    (root / "benchmarks" / "private_cases.json").write_text("private", encoding="utf-8")
    manifest = baseline().snapshot_source(root, tmp_path / "output")
    assert {item["path"] for item in manifest["files"]} == {
        "scripts/run.py", "benchmarks/retrieval_smoke.json",
    }


def test_runner_records_raw_cases_and_keeps_no_answer_separate():
    module = baseline()
    data = {"chunks": [{"source": "a.md", "chunk_id": 1, "text": "JWT"}],
            "cases": [{"id": "q1", "query": "JWT", "split": "smoke", "relevant_chunks": ["a.md#1"]},
                      {"id": "q2", "query": "zzzz", "split": "smoke", "relevant_chunks": []}]}
    rows = module.run_keyword(data, k=5, rounds=2, warmups=1)
    assert len(rows) == 4
    assert rows[0]["actual_chunks"] == ["a.md#1"]
    assert rows[1]["no_answer_correct"] is True
    assert all(row["elapsed_ms"] >= 0 for row in rows)


@pytest.mark.parametrize("k", [0, -1, True])
def test_invalid_k_is_rejected(k):
    with pytest.raises(ValueError):
        baseline().score_ranking([], [], k=k)
