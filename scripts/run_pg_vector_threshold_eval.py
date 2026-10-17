"""Measure vector no-answer thresholds on the approved retrieval dataset."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "study_task_assistant"))

from knowledge.embedding_retrieval import FastEmbedEmbeddingModel
from knowledge.knowledge_runtime import KnowledgeRuntimeConfig
from knowledge.retrieval_baseline import (active_chunk_ids, load_cases,
                                           require_experiment_database,
                                           score_ranking)
from storage.database import Database
from storage.pgvector_store import PgVectorConfig, PgVectorRetriever, PgVectorStore


def summarize_threshold_rows(rows):
    result = {}
    for threshold in sorted({row["threshold"] for row in rows}):
        subset = [row for row in rows if row["threshold"] == threshold]
        answered = [row["recall_at_5"] for row in subset if row["recall_at_5"] is not None]
        no_answer = [row["no_answer_correct"] for row in subset if row["no_answer_correct"] is not None]
        result[str(threshold)] = {
            "cases": len(subset),
            "mean_recall_at_5": mean(answered) if answered else None,
            "no_answer_accuracy": mean(no_answer) if no_answer else None,
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--owner-id", type=int, required=True)
    parser.add_argument("--thresholds", type=float, nargs="+", default=[0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8])
    parser.add_argument("--rounds", type=int, default=5)
    args = parser.parse_args()
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        parser.error("需要 TEST_DATABASE_URL")
    require_experiment_database(url)
    if args.output.exists():
        parser.error("--output 必须是新目录")
    payload = json.loads(args.cases.read_text(encoding="utf-8"))
    if payload.get("dataset_kind") != "human_labeled" or payload.get("review_status") != "approved":
        parser.error("只允许 approved human_labeled 数据集")
    config = KnowledgeRuntimeConfig.from_env()
    model = FastEmbedEmbeddingModel(config.model_name, config.threads, config.cache_dir)
    database = Database(url)
    rows = []
    try:
        known = active_chunk_ids(database.sessions, owner_id=args.owner_id)
        cases = load_cases(args.cases, known)
        retriever = PgVectorRetriever(database.sessions, model, PgVectorStore(PgVectorConfig(config.model_name, config.dimension)))
        for case in cases:
            for threshold in args.thresholds:
                for round_id in range(1, args.rounds + 1):
                    results = retriever.search(case["query"], owner_id=args.owner_id, limit=5, min_score=threshold)
                    actual = [f"{item.chunk.source}#{item.chunk.chunk_id}" for item in results]
                    scored = score_ranking(actual, case["relevant_chunks"], k=5)
                    rows.append({"case_id": case["id"], "split": case["split"], "threshold": threshold,
                                 "round": round_id, "actual_chunks": actual,
                                 "recall_at_5": scored["recall_at_k"],
                                 "no_answer_correct": scored["no_answer_correct"]})
    finally:
        database.dispose()
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "summary.json").write_text(json.dumps(summarize_threshold_rows(rows), ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output / "raw.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summarize_threshold_rows(rows), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
