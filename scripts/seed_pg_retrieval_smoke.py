"""Seed the public smoke fixture into an isolated, migrated study_tasks_eval DB."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "study_task_assistant"))

from knowledge.embedding_retrieval import FastEmbedEmbeddingModel
from knowledge.knowledge_runtime import KnowledgeRuntimeConfig
from knowledge.rag import DocumentChunk
from knowledge.retrieval_baseline import load_dataset, require_experiment_database
from storage.database import Database
from storage.models import Document, User
from storage.pgvector_store import PgVectorConfig, PgVectorStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=ROOT / "benchmarks/retrieval_smoke.json")
    parser.add_argument("--cases-output", type=Path, required=True)
    args = parser.parse_args()
    raw_url = os.environ.get("TEST_DATABASE_URL")
    if not raw_url:
        parser.error("需要 TEST_DATABASE_URL")
    try:
        require_experiment_database(raw_url)
    except ValueError as exc:
        parser.error(str(exc))
    dataset = load_dataset(args.fixture)
    if dataset.get("dataset_kind") != "synthetic_smoke":
        parser.error("此脚本只允许公开合成 smoke fixture")
    config = KnowledgeRuntimeConfig.from_env()
    model = FastEmbedEmbeddingModel(config.model_name, config.threads, config.cache_dir)
    chunks = [DocumentChunk(item["source"], item["chunk_id"], item["text"])
              for item in dataset["chunks"]]
    vectors = [(chunk, model.encode(chunk.text)) for chunk in chunks]
    if any(len(vector) != config.dimension for _, vector in vectors):
        raise ValueError("embedding 维度与实验库不一致")
    store = PgVectorStore(PgVectorConfig(config.model_name, config.dimension))
    database = Database(raw_url)
    try:
        with database.sessions.begin() as session:
            if session.scalar(select(User.id).where(User.username == "eval_smoke_v1")) is not None:
                raise ValueError("实验库已有 eval_smoke_v1，请使用全新实验库")
            user = User(username="eval_smoke_v1", password_hash="synthetic-fixture-no-login")
            session.add(user)
            session.flush()
            owner_id = user.id
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            sources = sorted({chunk.source for chunk in chunks})
            for source in sources:
                content = "\n".join(chunk.text for chunk in chunks if chunk.source == source)
                session.add(Document(
                    id=sha256(f"{owner_id}:{source}:smoke-v1".encode()).hexdigest()[:32],
                    owner_id=owner_id, source=source, document_version="smoke-v1",
                    content_hash=sha256(content.encode()).hexdigest(), state="ready",
                    active_version="smoke-v1", created_at=now, updated_at=now,
                ))
            session.flush()
            for chunk, vector in vectors:
                store.insert_chunk(session, owner_id=owner_id, chunk=chunk,
                                   vector=vector, document_version="smoke-v1")
    finally:
        database.dispose()
    args.cases_output.parent.mkdir(parents=True, exist_ok=True)
    args.cases_output.write_text(json.dumps({
        "version": dataset.get("version"),
        "dataset_kind": "synthetic_smoke",
        "cases": dataset["cases"],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"owner_id": owner_id, "chunks": len(chunks),
                      "cases": len(dataset["cases"]), "model": config.model_name},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
