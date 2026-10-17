"""Measure existing PostgreSQL keyword/vector/hybrid retrieval against labeled cases.

Requires TEST_DATABASE_URL, an already migrated experiment database, active
documents, and a case file whose labels refer to that owner's current chunks.
This command only reads from PostgreSQL and writes report files to --output.
"""

import argparse
import csv
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "study_task_assistant"))

from knowledge.embedding_retrieval import FastEmbedEmbeddingModel
from knowledge.hybrid_retrieval import HybridRetriever
from knowledge.keyword_retrieval import PgKeywordRetriever
from knowledge.knowledge_runtime import KnowledgeRuntimeConfig
from knowledge.retrieval_baseline import (
    active_chunk_ids, load_cases, require_experiment_database, run_scoped,
    snapshot_source, summarize_by_split, summarize_strategies,
)
from knowledge.retrieval_scale import capture_explain_plans, summarize_plan
from storage.database import Database
from storage.pgvector_store import PgVectorConfig, PgVectorRetriever, PgVectorStore


def git(*args):
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "unavailable"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--owner-id", type=int, required=True)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--allow-smoke", action="store_true")
    parser.add_argument("--allow-candidate", action="store_true")
    parser.add_argument("--capture-plans", action="store_true")
    args = parser.parse_args()
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        parser.error("TEST_DATABASE_URL 必须指向已迁移的独立 PostgreSQL 实验库")
    try:
        require_experiment_database(url)
    except ValueError as exc:
        parser.error(str(exc))
    if args.output.exists():
        parser.error("--output 必须是尚不存在的新目录")

    database = Database(url)
    try:
        known_chunks = active_chunk_ids(database.sessions, owner_id=args.owner_id)
        cases = load_cases(args.cases, known_chunks, allow_smoke=args.allow_smoke,
                           allow_candidate=args.allow_candidate)
        config = KnowledgeRuntimeConfig.from_env()
        model = FastEmbedEmbeddingModel(
            model_name=config.model_name, threads=config.threads,
            cache_dir=config.cache_dir,
        )
        if getattr(model, "model_name", None) != config.model_name:
            raise ValueError("embedding 模型与配置不一致")
        if len(tuple(model.encode("向量维度检查"))) != config.dimension:
            raise ValueError("embedding 维度与数据库配置不一致")
        store = PgVectorStore(PgVectorConfig(config.model_name, config.dimension))
        keyword = PgKeywordRetriever(database.sessions)
        vector = PgVectorRetriever(database.sessions, model, store)
        retrievers = {"keyword": keyword, "vector": vector,
                      "hybrid": HybridRetriever(keyword, vector)}
        rows = run_scoped(cases, retrievers, owner_id=args.owner_id, k=args.k,
                          rounds=args.rounds, warmups=args.warmups)
        plans = {}
        if args.capture_plans:
            for case in cases:
                plans[case["id"]] = capture_explain_plans(
                    database.sessions, owner_id=args.owner_id,
                    query_vector=tuple(model.encode(case["query"])),
                    model_name=config.model_name, dimension=config.dimension,
                    limit=args.k,
                )
    finally:
        database.dispose()

    args.output.mkdir(parents=True, exist_ok=False)
    snapshot = snapshot_source(ROOT, args.output / "snapshot")
    summary = summarize_strategies(rows)
    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "PostgreSQL current-owner active documents; no model generation",
        "strategies": list(retrievers),
        "owner_id": args.owner_id,
        "case_count": len(cases), "active_chunk_count": len(known_chunks),
        "dataset_kind": json.loads(args.cases.read_text(encoding="utf-8")).get(
            "dataset_kind", "synthetic_scale" if args.allow_smoke else "labeled"),
        "plan_modes": list(next(iter(plans.values()))) if plans else [],
        "plan_summary": {case_id: {mode: summarize_plan(plan) for mode, plan in modes.items()}
                         for case_id, modes in plans.items()},
        "case_file_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        "source_sha256": snapshot["source_sha256"],
        "git_head": git("rev-parse", "HEAD"),
        "git_status": git("status", "--porcelain"),
        "python": sys.version, "platform": platform.platform(),
        "processor": platform.processor(),
        "packages": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
        "model": config.model_name, "dimension": config.dimension,
        "threads": config.threads, "k": args.k,
        "rounds": args.rounds, "warmups": args.warmups,
        "command": [part for part in sys.argv if part != url],
        "database_url_recorded": False,
    }
    for name, value in [("metadata.json", metadata), ("cases.json", cases),
                        ("raw.json", rows), ("summary.json", summary),
                        ("plans.json", plans),
                        ("summary_by_split.json", summarize_by_split(rows))]:
        (args.output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    with (args.output / "raw.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({**row, "actual_chunks": json.dumps(row["actual_chunks"], ensure_ascii=False)}
                         for row in rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
