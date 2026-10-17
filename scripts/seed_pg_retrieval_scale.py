"""Seed 1,000 or 10,000 synthetic chunks into a fresh experiment database."""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "study_task_assistant"))

from knowledge.embedding_retrieval import FastEmbedEmbeddingModel
from knowledge.knowledge_runtime import KnowledgeRuntimeConfig
from knowledge.retrieval_baseline import load_dataset, require_experiment_database
from knowledge.retrieval_scale import build_scale_dataset
from storage.database import Database
from storage.models import Document, User


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, choices=(1000, 10000), required=True)
    parser.add_argument("--cases-output", type=Path, required=True)
    args = parser.parse_args()
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        parser.error("需要 TEST_DATABASE_URL")
    try:
        require_experiment_database(url)
    except ValueError as exc:
        parser.error(str(exc))
    base = load_dataset(ROOT / "benchmarks/retrieval_smoke.json")
    if base.get("dataset_kind") != "synthetic_smoke":
        parser.error("只允许公开合成 fixture")
    dataset = build_scale_dataset(base, args.size)
    config = KnowledgeRuntimeConfig.from_env()
    model = FastEmbedEmbeddingModel(config.model_name, config.threads, config.cache_dir)
    texts = {item["text"] for item in dataset["chunks"]}
    embeddings = {value: tuple(model.encode(value)) for value in texts}
    if any(len(vector) != config.dimension for vector in embeddings.values()):
        raise ValueError("embedding 维度与实验库不一致")
    vector_strings = {value: "[" + ",".join(str(x) for x in vector) + "]"
                      for value, vector in embeddings.items()}
    db = Database(url)
    try:
        with db.sessions.begin() as session:
            if session.scalar(select(User.id).where(User.username == "eval_scale_v1")):
                raise ValueError("实验库已有 eval_scale_v1，请使用全新实验库")
            user = User(username="eval_scale_v1", password_hash="synthetic-fixture-no-login")
            session.add(user)
            session.flush()
            owner_id = user.id
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            sources = {item["source"] for item in dataset["chunks"]}
            for source in sorted(sources):
                content = "\n".join(item["text"] for item in dataset["chunks"]
                                    if item["source"] == source)
                session.add(Document(
                    id=hashlib.sha256(f"{owner_id}:{source}:scale-v1".encode()).hexdigest()[:32],
                    owner_id=owner_id, source=source, document_version="scale-v1",
                    content_hash=hashlib.sha256(content.encode()).hexdigest(),
                    state="ready", active_version="scale-v1",
                    created_at=now, updated_at=now,
                ))
            session.flush()
            statement = text("""
                INSERT INTO document_chunks
                  (owner_id, source, chunk_id, content, embedding,
                   embedding_model, embedding_dimension, document_version)
                VALUES (:owner_id, :source, :chunk_id, :content,
                        CAST(:embedding AS vector), :embedding_model,
                        :embedding_dimension, 'scale-v1')
            """)
            for offset in range(0, args.size, 500):
                batch = dataset["chunks"][offset:offset + 500]
                session.execute(statement, [{
                    "owner_id": owner_id,
                    "source": item["source"], "chunk_id": item["chunk_id"],
                    "content": item["text"], "embedding": vector_strings[item["text"]],
                    "embedding_model": config.model_name,
                    "embedding_dimension": config.dimension,
                } for item in batch])
            session.execute(text("ANALYZE document_chunks"))
    finally:
        db.dispose()
    args.cases_output.parent.mkdir(parents=True, exist_ok=True)
    args.cases_output.write_text(json.dumps({
        "version": dataset["version"], "dataset_kind": "synthetic_scale",
        "cases": dataset["cases"],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"owner_id": owner_id, "chunks": args.size,
                      "unique_embedding_texts": len(texts),
                      "kind": "synthetic_scale"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
