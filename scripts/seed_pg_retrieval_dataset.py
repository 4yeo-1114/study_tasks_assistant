"""Seed an approved retrieval dataset into a fresh PostgreSQL experiment DB."""

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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--username", default="eval_labeled_v1")
    args = parser.parse_args()
    raw_url = os.environ.get("TEST_DATABASE_URL")
    if not raw_url:
        parser.error("需要 TEST_DATABASE_URL")
    try:
        require_experiment_database(raw_url)
    except ValueError as exc:
        parser.error(str(exc))

    dataset = load_dataset(args.fixture)
    if dataset.get("dataset_kind") != "human_labeled" or dataset.get("review_status") != "approved":
        parser.error("正式播种只接受 dataset_kind=human_labeled 且 review_status=approved")

    config = KnowledgeRuntimeConfig.from_env()
    model = FastEmbedEmbeddingModel(config.model_name, config.threads, config.cache_dir)
    chunks = [DocumentChunk(item["source"], item["chunk_id"], item["text"])
              for item in dataset["chunks"]]
    encode_many = getattr(model, "encode_many", None)
    vectors = list(encode_many([chunk.text for chunk in chunks]) if callable(encode_many)
                   else [model.encode(chunk.text) for chunk in chunks])
    if len(vectors) != len(chunks) or any(len(vector) != config.dimension for vector in vectors):
        raise ValueError("embedding 数量或维度与实验库配置不一致")

    database = Database(raw_url)
    store = PgVectorStore(PgVectorConfig(config.model_name, config.dimension))
    try:
        with database.sessions.begin() as session:
            if session.scalar(select(User.id).where(User.username == args.username)) is not None:
                raise ValueError(f"实验库已有 {args.username}，请使用全新实验库")
            user = User(username=args.username, password_hash="approved-fixture-no-login")
            session.add(user)
            session.flush()
            owner_id = user.id
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            for source in sorted({chunk.source for chunk in chunks}):
                content = "\n".join(chunk.text for chunk in chunks if chunk.source == source)
                version = "labeled-v1"
                session.add(Document(
                    id=sha256(f"{owner_id}:{source}:{version}".encode()).hexdigest()[:32],
                    owner_id=owner_id, source=source, document_version=version,
                    content_hash=sha256(content.encode()).hexdigest(), state="ready",
                    active_version=version, created_at=now, updated_at=now,
                ))
            session.flush()
            for chunk, vector in zip(chunks, vectors):
                store.insert_chunk(session, owner_id=owner_id, chunk=chunk,
                                   vector=vector, document_version="labeled-v1")
    finally:
        database.dispose()
    print(json.dumps({"owner_id": owner_id, "chunks": len(chunks),
                      "cases": len(dataset["cases"]), "dataset": str(args.fixture)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
