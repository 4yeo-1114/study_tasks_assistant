"""Compare exact and planner-default vector search on diverse synthetic vectors.

Use only a fresh, migrated study_tasks_eval PostgreSQL database.  The seeded
vectors are deterministic random data, not FastEmbed outputs or user content.
"""

import argparse
import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "study_task_assistant"))

from knowledge.knowledge_runtime import KnowledgeRuntimeConfig
from knowledge.retrieval_baseline import require_experiment_database, snapshot_source
from knowledge.retrieval_scale import (
    bare_vector_sql, deterministic_vector, explain_vector_sql, filtered_vector_sql,
    neighbor_overlap, summarize_plan,
)
from storage.database import Database
from storage.models import Document, User


def git_head():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                              check=True, capture_output=True, text=True).stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "unavailable"


def pgvector_string(values):
    return "[" + ",".join(str(value) for value in values) + "]"


def query_once(sessions, sql, params, *, mode):
    with sessions.begin() as session:
        if mode == "exact":
            session.execute(text("SET LOCAL enable_indexscan = off"))
            session.execute(text("SET LOCAL enable_bitmapscan = off"))
        elif mode == "force_index":
            session.execute(text("SET LOCAL enable_seqscan = off"))
            session.execute(text("SET LOCAL enable_bitmapscan = off"))
            session.execute(text("SET LOCAL enable_sort = off"))
        started = time.perf_counter()
        rows = session.execute(text(sql), params).all()
        elapsed_ms = (time.perf_counter() - started) * 1000
    return [f"{row.source}#{row.chunk_id}" for row in rows], elapsed_ms


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--size", type=int, choices=(1000, 10000), default=10000)
    parser.add_argument("--queries", type=int, default=20)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--candidate-limit", type=int, default=100)
    parser.add_argument("--reuse", action="store_true", help="reuse existing probe rows in the experiment DB")
    args = parser.parse_args()
    if args.queries < 1 or args.queries > args.size or args.rounds < 1 or args.k < 1 or args.candidate_limit < args.k:
        parser.error("queries/rounds/k/candidate-limit 必须为有效正整数，candidate-limit 不得小于 k")
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        parser.error("需要 TEST_DATABASE_URL")
    try:
        require_experiment_database(url)
    except ValueError as exc:
        parser.error(str(exc))
    if args.output.exists():
        parser.error("--output 必须是新目录")

    config = KnowledgeRuntimeConfig.from_env()
    db = Database(url)
    source = "hnsw-probe.md"
    version = "random-vector-v1"
    digest = hashlib.sha256()
    try:
        with db.sessions.begin() as session:
            existing_id = session.scalar(select(User.id).where(User.username == "eval_hnsw_probe_v1"))
            if args.reuse:
                if existing_id is None:
                    raise ValueError("实验库没有可复用的 probe 用户")
                count = session.scalar(text("SELECT count(*) FROM document_chunks WHERE owner_id = :owner_id"),
                                       {"owner_id": existing_id})
                if count != args.size:
                    raise ValueError("现有 chunk 数与 --size 不一致")
                owner_id = existing_id
            else:
                if existing_id is not None:
                    raise ValueError("实验库已有 eval_hnsw_probe_v1，请使用全新实验库")
                user = User(username="eval_hnsw_probe_v1", password_hash="synthetic-fixture-no-login")
                session.add(user)
                session.flush()
                owner_id = user.id
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                session.add(Document(
                    id=hashlib.sha256(f"{owner_id}:{source}:{version}".encode()).hexdigest()[:32],
                    owner_id=owner_id, source=source, document_version=version,
                    content_hash=hashlib.sha256(f"synthetic:{args.size}".encode()).hexdigest(),
                    state="ready", active_version=version, created_at=now, updated_at=now,
                ))
                session.flush()
            if not args.reuse:
                insert = text("""
                    INSERT INTO document_chunks
                      (owner_id, source, chunk_id, content, embedding,
                       embedding_model, embedding_dimension, document_version)
                    VALUES (:owner_id, :source, :chunk_id, :content,
                            CAST(:embedding AS vector), :embedding_model,
                            :embedding_dimension, :document_version)
                """)
                for start in range(1, args.size + 1, 250):
                    batch = []
                    for chunk_id in range(start, min(start + 250, args.size + 1)):
                        vector = pgvector_string(deterministic_vector(chunk_id, dimension=config.dimension))
                        digest.update(f"{chunk_id}:{vector}\n".encode("ascii"))
                        batch.append({"owner_id": owner_id, "source": source,
                                      "chunk_id": chunk_id, "content": f"synthetic vector {chunk_id}",
                                      "embedding": vector, "embedding_model": config.model_name,
                                      "embedding_dimension": config.dimension,
                                      "document_version": version})
                    session.execute(insert, batch)
                session.execute(text("ANALYZE document_chunks"))

        ids = [1 + (index * (args.size - 1) // max(args.queries - 1, 1))
               for index in range(args.queries)]
        if args.queries == 1:
            ids = [1]
        sql_by_mode = {"bare": bare_vector_sql(),
                       "production_join": explain_vector_sql(explain=False),
                       "filtered_join": filtered_vector_sql(
                           explain=False, candidate_limit=args.candidate_limit)}
        rows = []
        plans = {}
        for query_id in ids:
            params = {"owner_id": owner_id, "embedding_model": config.model_name,
                      "embedding_dimension": config.dimension, "limit": args.k,
                      "candidate_limit": args.candidate_limit,
                      "query_vector": pgvector_string(deterministic_vector(
                          query_id, dimension=config.dimension))}
            for scope, sql in sql_by_mode.items():
                for mode in ("planner_default", "exact", "force_index"):
                    query_once(db.sessions, sql, params, mode=mode)
            if query_id == ids[0]:
                for scope, sql in (("bare", bare_vector_sql(explain=True)),
                                   ("production_join", explain_vector_sql()),
                                   ("filtered_join", filtered_vector_sql(
                                       explain=True, candidate_limit=args.candidate_limit))):
                    for mode in ("planner_default", "exact", "force_index"):
                        with db.sessions.begin() as session:
                            if mode == "exact":
                                session.execute(text("SET LOCAL enable_indexscan = off"))
                                session.execute(text("SET LOCAL enable_bitmapscan = off"))
                            elif mode == "force_index":
                                session.execute(text("SET LOCAL enable_seqscan = off"))
                                session.execute(text("SET LOCAL enable_bitmapscan = off"))
                                session.execute(text("SET LOCAL enable_sort = off"))
                            plan_params = {**params, "candidate_limit": args.candidate_limit}
                            plan = session.execute(text(sql), plan_params).scalar()
                        plans[f"{scope}_{mode}"] = plan
            for round_number in range(1, args.rounds + 1):
                for scope, sql in sql_by_mode.items():
                    exact_ids, exact_ms = query_once(db.sessions, sql, params, mode="exact")
                    rows.append(
                        {"scope": scope, "mode": "exact", "query_id": query_id,
                         "round": round_number, "neighbors": exact_ids,
                         "elapsed_ms": exact_ms, "overlap_at_k": 1.0})
                    for mode in ("planner_default", "force_index"):
                        actual_ids, elapsed_ms = query_once(db.sessions, sql, params, mode=mode)
                        rows.append({"scope": scope, "mode": mode, "query_id": query_id,
                                     "round": round_number, "neighbors": actual_ids,
                                     "elapsed_ms": elapsed_ms,
                                     "overlap_at_k": neighbor_overlap(actual_ids, exact_ids, k=args.k)})
    finally:
        db.dispose()

    args.output.mkdir(parents=True, exist_ok=False)
    snapshot = snapshot_source(ROOT, args.output / "snapshot")
    summaries = {}
    for scope in sql_by_mode:
        for mode in ("exact", "planner_default", "force_index"):
            subset = [row for row in rows if row["scope"] == scope and row["mode"] == mode]
            elapsed = sorted(row["elapsed_ms"] for row in subset)
            def percentile(p):
                position = (len(elapsed) - 1) * p
                low = int(position)
                return elapsed[low] + (elapsed[min(low + 1, len(elapsed) - 1)] - elapsed[low]) * (position - low)
            summaries[f"{scope}_{mode}"] = {
                "samples": len(subset), "unique_queries": len(ids),
                "p50_ms": percentile(0.5), "p95_ms": percentile(0.95),
                "mean_overlap_at_k": sum(row["overlap_at_k"] for row in subset) / len(subset),
            }
    plan_summary = {name: summarize_plan(plan) for name, plan in plans.items()}
    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_kind": "synthetic_random_vectors_not_model_embeddings",
        "size": args.size, "queries": len(ids), "rounds": args.rounds, "k": args.k,
        "candidate_limit": args.candidate_limit,
        "reused_seed": args.reuse,
        "vector_seed": "random.Random(chunk_id)",
        "vector_sha256": digest.hexdigest() if not args.reuse else None,
        "reuse_validation": "owner row count only" if args.reuse else "fresh insert",
        "embedding_model_filter": config.model_name, "dimension": config.dimension,
        "source_sha256": snapshot["source_sha256"], "git_head": git_head(),
        "platform": platform.platform(), "python": sys.version,
        "plan_summary": plan_summary, "database_url_recorded": False,
    }
    for name, payload in (("metadata.json", metadata), ("raw.json", rows),
                          ("summary.json", summaries), ("plans.json", plans)):
        (args.output / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    with (args.output / "raw.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({**row, "neighbors": json.dumps(row["neighbors"])} for row in rows)
    print(json.dumps({"summary": summaries, "plan_summary": plan_summary},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
