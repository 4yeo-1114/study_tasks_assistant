"""Evaluate ANN candidate windows against exact production retrieval.

Uses the approved human-labeled set and an existing isolated PostgreSQL DB.
The comparison measures whether filtering after an ANN candidate window drops
the exact top-k results; it does not claim an HNSW speedup by itself.
"""

import argparse
import csv
import hashlib
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "study_task_assistant"))

from knowledge.embedding_retrieval import FastEmbedEmbeddingModel
from knowledge.knowledge_runtime import KnowledgeRuntimeConfig
from knowledge.retrieval_baseline import (active_chunk_ids, load_cases,
                                           require_experiment_database,
                                           snapshot_source)
from knowledge.retrieval_scale import filtered_vector_sql
from storage.database import Database


def exact_sql():
    return """
    SELECT dc.source, dc.chunk_id, dc.embedding <=> CAST(:query_vector AS vector) AS distance
    FROM document_chunks dc JOIN documents d
      ON d.owner_id = dc.owner_id AND d.source = dc.source
     AND d.document_version = dc.document_version
    WHERE dc.owner_id = :owner_id AND dc.embedding_model = :embedding_model
      AND dc.embedding_dimension = :embedding_dimension
      AND d.state = 'ready' AND d.active_version = dc.document_version
    ORDER BY dc.embedding <=> CAST(:query_vector AS vector) LIMIT :limit
    """


def ids(session, sql, params):
    return [f"{row.source}#{row.chunk_id}" for row in session.execute(text(sql), params).all()]


def percentile(values, p):
    ordered = sorted(values)
    position = (len(ordered) - 1) * p
    low = int(position)
    return ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (position - low)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--owner-id", type=int, required=True)
    parser.add_argument("--limits", type=int, nargs="+", default=[5, 10, 20, 50, 100])
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    args = parser.parse_args()
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        parser.error("需要 TEST_DATABASE_URL")
    require_experiment_database(url)
    if args.output.exists() or any(x < 5 for x in args.limits):
        parser.error("--output 必须是新目录，limits 必须不小于 k=5")
    dataset = json.loads(args.cases.read_text(encoding="utf-8"))
    if dataset.get("dataset_kind") != "human_labeled" or dataset.get("review_status") != "approved":
        parser.error("只允许 approved human_labeled 数据集")
    config = KnowledgeRuntimeConfig.from_env()
    model = FastEmbedEmbeddingModel(config.model_name, config.threads, config.cache_dir)
    db = Database(url)
    try:
        known = active_chunk_ids(db.sessions, owner_id=args.owner_id)
        cases = load_cases(args.cases, known)
        exact = exact_sql()
        rows = []
        for case in cases:
            vector = tuple(model.encode(case["query"]))
            vector_text = "[" + ",".join(str(float(x)) for x in vector) + "]"
            base = {"owner_id": args.owner_id, "embedding_model": config.model_name,
                    "embedding_dimension": config.dimension, "query_vector": vector_text,
                    "limit": 5}
            with db.sessions.begin() as session:
                exact_ids = ids(session, exact, base)
            for candidate_limit in args.limits:
                sql = filtered_vector_sql(candidate_limit=candidate_limit)
                params = {**base, "candidate_limit": candidate_limit}
                for _ in range(args.warmups):
                    with db.sessions.begin() as session:
                        ids(session, sql, params)
                for round_number in range(1, args.rounds + 1):
                    with db.sessions.begin() as session:
                        started = time.perf_counter()
                        actual = ids(session, sql, params)
                        elapsed = (time.perf_counter() - started) * 1000
                    overlap = len(set(actual[:5]) & set(exact_ids[:5])) / min(5, len(exact_ids)) if exact_ids else 1.0
                    rows.append({"case_id": case["id"], "split": case["split"],
                                 "candidate_limit": candidate_limit, "round": round_number,
                                 "exact_ids": exact_ids, "actual_ids": actual,
                                 "overlap_at_5": overlap, "elapsed_ms": elapsed})
    finally:
        db.dispose()
    args.output.mkdir(parents=True, exist_ok=False)
    snap = snapshot_source(ROOT, args.output / "snapshot")
    summaries = {}
    for limit in args.limits:
        subset = [r for r in rows if r["candidate_limit"] == limit]
        summaries[str(limit)] = {
            "samples": len(subset), "cases": len(cases), "rounds": args.rounds,
            "mean_overlap_at_5": statistics.mean(r["overlap_at_5"] for r in subset),
            "p50_ms": percentile([r["elapsed_ms"] for r in subset], .5),
            "p95_ms": percentile([r["elapsed_ms"] for r in subset], .95),
            "exact_match_rate": sum(r["overlap_at_5"] == 1.0 for r in subset) / len(subset),
        }
    metadata = {"created_at_utc": datetime.now(timezone.utc).isoformat(),
                "dataset_kind": dataset["dataset_kind"], "review_status": dataset["review_status"],
                "case_file_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
                "owner_id": args.owner_id, "limits": args.limits, "k": 5,
                "rounds": args.rounds, "warmups": args.warmups,
                "model": config.model_name, "dimension": config.dimension,
                "source_sha256": snap["source_sha256"], "database_url_recorded": False}
    (args.output / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output / "summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output / "raw.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    with (args.output / "raw.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["case_id", "split", "candidate_limit", "round", "overlap_at_5", "elapsed_ms", "exact_ids", "actual_ids"])
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "exact_ids": json.dumps(row["exact_ids"], ensure_ascii=False), "actual_ids": json.dumps(row["actual_ids"], ensure_ascii=False)})
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
