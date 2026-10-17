"""Reproducible, dependency-light retrieval baseline experiments.

This module intentionally measures the current in-memory keyword retriever and
keeps dataset, source snapshot, quality metrics, and raw timings separate.
It is an experiment harness, not a production request path.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import zipfile
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Sequence

from sqlalchemy import text
from sqlalchemy.engine import make_url

from knowledge.hybrid_retrieval import RetrievalFilters
from knowledge.rag import DocumentChunk, KeywordRetriever


def _validate_k(k: int) -> None:
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("k 必须是正整数")


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def score_ranking(
    actual_chunks: Sequence[str],
    relevant_chunks: Sequence[str],
    *,
    k: int,
) -> dict[str, float | bool | None]:
    """Score one query; no-answer cases are kept separate from retrieval rates."""
    _validate_k(k)
    actual = list(actual_chunks[:k])
    relevant = set(relevant_chunks)
    if not relevant:
        return {
            "recall_at_k": None,
            "reciprocal_rank_at_k": None,
            "no_answer_correct": not actual,
        }
    hits = len(set(actual) & relevant)
    reciprocal_rank = next(
        (1.0 / (index + 1) for index, chunk in enumerate(actual) if chunk in relevant),
        0.0,
    )
    return {
        "recall_at_k": hits / len(relevant),
        "reciprocal_rank_at_k": reciprocal_rank,
        "no_answer_correct": None,
    }


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise ValueError("至少需要一个耗时样本")
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, float | int | None]:
    if not rows:
        raise ValueError("rows 不能为空")
    answered = [row for row in rows if row["recall_at_k"] is not None]
    no_answer = [row for row in rows if row["no_answer_correct"] is not None]
    elapsed = [float(row["elapsed_ms"]) for row in rows]
    return {
        "cases": len(rows),
        "mean_recall_at_k": mean(row["recall_at_k"] for row in answered) if answered else None,
        "mrr_at_k": mean(row["reciprocal_rank_at_k"] for row in answered) if answered else None,
        "no_answer_accuracy": mean(row["no_answer_correct"] for row in no_answer) if no_answer else None,
        "p50_ms": _percentile(elapsed, 0.50),
        "p95_ms": _percentile(elapsed, 0.95),
    }


def _parse_chunk_id(value: str) -> tuple[str, int]:
    source, separator, raw_id = value.rpartition("#")
    if not separator or not source or not raw_id.isdigit() or int(raw_id) < 1:
        raise ValueError(f"chunk id 格式不合法: {value!r}")
    return source, int(raw_id)


def load_dataset(path: str | Path) -> dict[str, Any]:
    """Load and validate a versioned retrieval dataset."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("数据集不是合法 JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("chunks"), list) or not isinstance(payload.get("cases"), list):
        raise ValueError("数据集必须包含 chunks 和 cases 列表")
    known: set[str] = set()
    chunks: list[DocumentChunk] = []
    for raw in payload["chunks"]:
        try:
            chunk = DocumentChunk(str(raw["source"]), int(raw["chunk_id"]), str(raw["text"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("chunk 格式不合法") from exc
        key = f"{chunk.source}#{chunk.chunk_id}"
        if key in known:
            raise ValueError(f"duplicate chunk: {key}")
        known.add(key)
        chunks.append(chunk)
    case_ids: set[str] = set()
    cases: list[dict[str, Any]] = []
    if not payload["cases"]:
        raise ValueError("cases 不能为空")
    for raw in payload["cases"]:
        if not isinstance(raw, dict):
            raise ValueError("case 格式不合法")
        case_id = str(raw.get("id", ""))
        if not case_id:
            raise ValueError("case 缺少 id")
        if case_id in case_ids:
            raise ValueError(f"duplicate case: {case_id}")
        case_ids.add(case_id)
        split = str(raw.get("split", ""))
        if split not in {"development", "frozen", "smoke"}:
            raise ValueError(f"case 缺少 split: {case_id}")
        query = raw.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"case query 不能为空: {case_id}")
        raw_relevant = raw.get("relevant_chunks", [])
        if not isinstance(raw_relevant, list):
            raise ValueError(f"relevant_chunks 必须是列表: {case_id}")
        relevant = [str(item) for item in raw_relevant]
        for item in relevant:
            _parse_chunk_id(item)
            if item not in known:
                raise ValueError(f"unknown chunk in case {case_id}: {item}")
        cases.append({"id": case_id, "query": query, "split": split, "relevant_chunks": relevant})
    payload = dict(payload)
    payload["chunks"] = [{"source": c.source, "chunk_id": c.chunk_id, "text": c.text} for c in chunks]
    payload["cases"] = cases
    return payload


def run_keyword(
    dataset: dict[str, Any], *, k: int = 5, rounds: int = 5, warmups: int = 1
) -> list[dict[str, Any]]:
    _validate_k(k)
    if isinstance(rounds, bool) or not isinstance(rounds, int) or rounds < 1 or warmups < 0:
        raise ValueError("rounds 必须为正整数，warmups 不能为负数")
    chunks = [DocumentChunk(str(x["source"]), int(x["chunk_id"]), str(x["text"])) for x in dataset["chunks"]]
    retriever = KeywordRetriever(chunks)
    cases = list(dataset["cases"])
    for _ in range(warmups):
        for case in cases:
            retriever.search(str(case["query"]), limit=k)
    rows: list[dict[str, Any]] = []
    for round_id in range(1, rounds + 1):
        for case in cases:
            started = time.perf_counter()
            results = retriever.search(str(case["query"]), limit=k)
            elapsed_ms = (time.perf_counter() - started) * 1000
            actual = [f"{item.chunk.source}#{item.chunk.chunk_id}" for item in results]
            scored = score_ranking(actual, case["relevant_chunks"], k=k)
            rows.append({"round": round_id, "case_id": case["id"], "split": case["split"], "query": case["query"], "actual_chunks": actual, "elapsed_ms": elapsed_ms, **scored})
    return rows


def active_chunk_ids(sessions: Any, *, owner_id: int) -> set[str]:
    """Read label IDs visible to one owner in the production retrieval scope."""
    if isinstance(owner_id, bool) or not isinstance(owner_id, int) or owner_id < 1:
        raise ValueError("owner_id 必须是正整数")
    with sessions() as session:
        rows = session.execute(text("""
            SELECT document_chunks.source, document_chunks.chunk_id
            FROM document_chunks
            JOIN documents
              ON documents.owner_id = document_chunks.owner_id
             AND documents.source = document_chunks.source
             AND documents.document_version = document_chunks.document_version
            WHERE document_chunks.owner_id = :owner_id
              AND documents.state = 'ready'
              AND documents.active_version = document_chunks.document_version
        """), {"owner_id": owner_id})
        return {f"{row.source}#{row.chunk_id}" for row in rows}


def require_experiment_database(url: str) -> None:
    """Refuse to run baseline experiments against the normal application DB."""
    parsed = make_url(url)
    if not parsed.drivername.startswith("postgresql+") or parsed.database != "study_tasks_eval":
        raise ValueError("TEST_DATABASE_URL 必须指向独立的 study_tasks_eval PostgreSQL 数据库")


def load_cases(
    path: str | Path,
    known_chunks: set[str],
    *,
    allow_smoke: bool = False,
    allow_candidate: bool = False,
) -> list[dict[str, Any]]:
    """Validate query labels against the current owner's active chunks."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("评测问题文件不是合法 JSON") from exc
    raw_cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("评测问题文件必须包含非空 cases 列表")
    if payload.get("dataset_kind") == "ai_generated_candidate" and not allow_candidate:
        raise ValueError("AI 生成候选题集必须显式传入 allow_candidate")
    case_ids: set[str] = set()
    cases: list[dict[str, Any]] = []
    for raw in raw_cases:
        if not isinstance(raw, dict):
            raise ValueError("case 格式不合法")
        case_id = raw.get("id")
        query = raw.get("query")
        split = raw.get("split")
        relevant = raw.get("relevant_chunks")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in case_ids:
            raise ValueError(f"case id 为空或 duplicate: {case_id!r}")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"case query 为空: {case_id}")
        allowed_splits = {"development", "frozen", "smoke"} if allow_smoke else {"development", "frozen"}
        if split not in allowed_splits:
            raise ValueError(f"case split 不合法: {case_id}")
        if not isinstance(relevant, list) or any(not isinstance(item, str) for item in relevant):
            raise ValueError(f"relevant_chunks 必须是字符串列表: {case_id}")
        for item in relevant:
            _parse_chunk_id(item)
            if item not in known_chunks:
                raise ValueError(f"unknown or inactive chunk in case {case_id}: {item}")
        case_ids.add(case_id)
        cases.append({"id": case_id, "query": query, "split": split,
                      "relevant_chunks": _unique(relevant)})
    return cases


def run_scoped(
    cases: Sequence[dict[str, Any]],
    retrievers: dict[str, Any],
    *,
    owner_id: int,
    k: int = 5,
    rounds: int = 5,
    warmups: int = 1,
) -> list[dict[str, Any]]:
    """Measure the existing production retrievers under the same query set."""
    _validate_k(k)
    if isinstance(owner_id, bool) or not isinstance(owner_id, int) or owner_id < 1:
        raise ValueError("owner_id 必须是正整数")
    if not cases or not retrievers or isinstance(rounds, bool) or not isinstance(rounds, int) or rounds < 1 or isinstance(warmups, bool) or not isinstance(warmups, int) or warmups < 0:
        raise ValueError("cases/retrievers 不能为空，rounds/warmups 必须有效")
    if set(retrievers) - {"keyword", "vector", "hybrid"}:
        raise ValueError("存在不支持的检索策略")

    def search(strategy: str, query: str):
        retriever = retrievers[strategy]
        if strategy == "hybrid":
            return retriever.search(query, limit=k, filters=RetrievalFilters(owner_id=owner_id))
        return retriever.search(query, owner_id=owner_id, limit=k)

    for _ in range(warmups):
        for case in cases:
            for strategy in retrievers:
                search(strategy, case["query"])
    rows: list[dict[str, Any]] = []
    for round_id in range(1, rounds + 1):
        for case in cases:
            for strategy in retrievers:
                started = time.perf_counter()
                results = search(strategy, case["query"])
                elapsed_ms = (time.perf_counter() - started) * 1000
                actual = [f"{item.chunk.source}#{item.chunk.chunk_id}" for item in results]
                rows.append({"round": round_id, "case_id": case["id"],
                             "split": case["split"], "strategy": strategy,
                             "actual_chunks": actual, "elapsed_ms": elapsed_ms,
                             **score_ranking(actual, case["relevant_chunks"], k=k)})
    return rows


def summarize_strategies(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, float | int | None]]:
    strategies = list(dict.fromkeys(row["strategy"] for row in rows))
    return {strategy: summarize([row for row in rows if row["strategy"] == strategy])
            for strategy in strategies}


def summarize_by_split(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, dict[str, float | int | None]]]:
    splits = list(dict.fromkeys(row["split"] for row in rows))
    grouped = {}
    for split in splits:
        split_rows = [row for row in rows if row["split"] == split]
        grouped[split] = summarize_strategies(split_rows)
        for strategy, summary in grouped[split].items():
            summary["unique_queries"] = len({row["case_id"] for row in split_rows
                                              if row["strategy"] == strategy})
    return grouped


_EXCLUDED_PARTS = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
_EXCLUDED_NAMES = {".env", "tasks.json", "tasks.db", "study_tasks.db"}


def snapshot_source(root: str | Path, output: str | Path) -> dict[str, Any]:
    """Create a source-only zip and manifest, excluding secrets/runtime state."""
    root_path = Path(root).resolve()
    output_path = Path(output).resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    allowed_roots = {"study_task_assistant", "tests", ".github", "scripts", "benchmarks"}
    allowed_root_files = {"pytest.ini", "README.md", ".gitignore"}
    allowed_names = {"Dockerfile", ".env.example", ".env.compose.example", "requirements.txt"}
    allowed_suffixes = {".py", ".md", ".html", ".css", ".js", ".ini", ".yaml", ".yml", ".mako"}
    candidates = [root_path / name for name in allowed_root_files]
    for allowed_root in allowed_roots:
        directory = root_path / allowed_root
        if not directory.is_dir() or directory.is_symlink():
            continue
        for current, directories, filenames in os.walk(directory):
            directories[:] = [name for name in directories if name not in _EXCLUDED_PARTS]
            candidates.extend(Path(current) / name for name in filenames)
    for path in sorted(candidates):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root_path)
        if relative.as_posix() == "benchmarks/retrieval_smoke.json":
            allowed = True
        else:
            allowed = path.suffix in allowed_suffixes or path.name in allowed_names
        if relative.parts[0] not in allowed_roots and relative.as_posix() not in allowed_root_files:
            continue
        if not allowed:
            continue
        if path.name in _EXCLUDED_NAMES or path.suffix in {".db", ".sqlite", ".sqlite3", ".dump"}:
            continue
        files.append(path)
    zip_path = output_path / "source.zip"
    digest = hashlib.sha256()
    entries = []
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            name = path.relative_to(root_path).as_posix()
            content = path.read_bytes()
            file_hash = hashlib.sha256(content).hexdigest()
            digest.update(name.encode("utf-8") + b"\0" + file_hash.encode("ascii") + b"\n")
            archive.writestr(zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)), content)
            entries.append({"path": name, "sha256": file_hash})
    manifest = {"root": str(root_path), "file_count": len(files), "source_sha256": digest.hexdigest(), "files": entries, "excluded_runtime_state": True}
    (output_path / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
