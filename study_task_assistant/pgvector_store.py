from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from embedding_retrieval import EmbeddingModel, VectorSearchResult
from rag import DocumentChunk


@dataclass(frozen=True)
class PgVectorConfig:
    model_name: str
    dimension: int

    def __post_init__(self) -> None:
        if not self.model_name.strip():
            raise ValueError("model_name 不能为空")
        if self.dimension < 1:
            raise ValueError("dimension 必须大于 0")


CREATE_EXTENSION_SQL = text("CREATE EXTENSION IF NOT EXISTS vector")

def create_table_sql(config: PgVectorConfig):
    """Build DDL with a validated, literal vector dimension."""
    return text(f"""
    CREATE TABLE IF NOT EXISTS document_chunks (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        owner_id BIGINT NOT NULL REFERENCES users(id),
        source TEXT NOT NULL,
        chunk_id INTEGER NOT NULL CHECK (chunk_id > 0),
        content TEXT NOT NULL CHECK (btrim(content) <> ''),
        embedding vector({config.dimension}) NOT NULL,
        embedding_model TEXT NOT NULL,
        embedding_dimension INTEGER NOT NULL,
        document_version TEXT NOT NULL,
        UNIQUE (owner_id, source, chunk_id, document_version)
    )
    """)


@dataclass(frozen=True)
class PgVectorStore:
    config: PgVectorConfig

    def delete_document(self, session: Session, *, owner_id: int, source: str) -> int:
        """Delete every indexed version of one owner's source document."""
        if not source.strip():
            raise ValueError("source 不能为空")
        result = session.execute(
            text("""
            DELETE FROM document_chunks
            WHERE owner_id = :owner_id AND source = :source
            """),
            {"owner_id": owner_id, "source": source},
        )
        return int(result.rowcount or 0)

    def delete_document_version(
        self,
        session: Session,
        *,
        owner_id: int,
        source: str,
        document_version: str,
    ) -> int:
        """Delete only one version so an older active version can remain queryable."""
        if not source.strip():
            raise ValueError("source 不能为空")
        if not document_version.strip():
            raise ValueError("document_version 不能为空")
        result = session.execute(
            text("""
            DELETE FROM document_chunks
            WHERE owner_id = :owner_id
              AND source = :source
              AND document_version = :document_version
            """),
            {
                "owner_id": owner_id,
                "source": source,
                "document_version": document_version,
            },
        )
        return int(result.rowcount or 0)
    def insert_chunk(
        self,
        session: Session,
        *,
        owner_id: int,
        chunk: DocumentChunk,
        vector: Sequence[float],
        document_version: str,
    ) -> None:
        values = tuple(float(item) for item in vector)
        self._validate_vector(values)
        if not document_version.strip():
            raise ValueError("document_version 不能为空")
        session.execute(
            text("""
            INSERT INTO document_chunks (
                owner_id, source, chunk_id, content, embedding,
                embedding_model, embedding_dimension, document_version
            ) VALUES (
                :owner_id, :source, :chunk_id, :content,
                CAST(:embedding AS vector), :embedding_model,
                :embedding_dimension, :document_version
            )
            """),
            {
                "owner_id": owner_id,
                "source": chunk.source,
                "chunk_id": chunk.chunk_id,
                "content": chunk.text,
                "embedding": self._as_pgvector(values),
                "embedding_model": self.config.model_name,
                "embedding_dimension": self.config.dimension,
                "document_version": document_version,
            },
        )

    def search(
        self,
        session: Session,
        *,
        owner_id: int,
        query_vector: Sequence[float],
        limit: int = 3,
        source: str | None = None,
        document_version: str | None = None,
    ) -> list[VectorSearchResult]:
        values = tuple(float(item) for item in query_vector)
        self._validate_vector(values)
        if limit < 1:
            raise ValueError("limit 必须大于 0")
        if source is not None and not source.strip():
            raise ValueError("source 不能为空")
        if document_version is not None and not document_version.strip():
            raise ValueError("document_version 不能为空")

        conditions = [
            "document_chunks.owner_id = :owner_id",
            "document_chunks.embedding_model = :embedding_model",
            "document_chunks.embedding_dimension = :embedding_dimension",
            "documents.state = 'ready'",
            #当前chunk必须属于激活版本
            "documents.active_version = document_chunks.document_version",
        ]
        params = {
            "owner_id": owner_id,
            "query_vector": self._as_pgvector(values),
            "embedding_model": self.config.model_name,
            "embedding_dimension": self.config.dimension,
            "limit": limit,
        }
        if source is not None:
            conditions.append("document_chunks.source = :source")
            params["source"] = source
        if document_version is not None:
            conditions.append("document_chunks.document_version = :document_version")
            params["document_version"] = document_version

        rows = session.execute(
            text(f"""
            SELECT document_chunks.source, document_chunks.chunk_id, document_chunks.content,
                   document_chunks.embedding <=> CAST(:query_vector AS vector) AS distance
            FROM document_chunks
            JOIN documents
              ON documents.owner_id = document_chunks.owner_id
             AND documents.source = document_chunks.source
             AND documents.document_version = document_chunks.document_version
            WHERE {" AND ".join(conditions)}
            ORDER BY document_chunks.embedding <=> CAST(:query_vector AS vector)
            LIMIT :limit
            """),
            params,
        )
        return [
            VectorSearchResult(
                chunk=DocumentChunk(row.source, row.chunk_id, row.content),
                score=1.0 - float(row.distance),
            )
            for row in rows
        ]

    def _validate_vector(self, vector: Sequence[float]) -> None:
        if len(vector) != self.config.dimension:
            raise ValueError("向量维度与 pgvector 配置不一致")

    @staticmethod
    def _as_pgvector(vector: Sequence[float]) -> str:
        return "[" + ",".join(str(value) for value in vector) + "]"


class PgVectorRetriever:
    """Adapter that gives PgVectorStore the same query-facing shape as VectorRetriever."""

    def __init__(self, sessions: Any, model: EmbeddingModel, store: PgVectorStore) -> None:
        self._sessions = sessions
        self._model = model
        self._store = store

    def search(
        self,
        query: str,
        *,
        owner_id: int,
        limit: int = 3,
        min_score: float = -1.0,
        source: str | None = None,
        document_version: str | None = None,
    ) -> list[VectorSearchResult]:
        if not query.strip():
            raise ValueError("问题不能为空")
        if limit < 1:
            raise ValueError("limit 必须大于 0")
        if not -1 <= min_score <= 1:
            raise ValueError("min_score 必须在 -1 到 1 之间")
        if source is not None and not source.strip():
            raise ValueError("source 不能为空")
        if document_version is not None and not document_version.strip():
            raise ValueError("document_version 不能为空")

        query_vector = self._model.encode(query)
        with self._sessions() as session:
            results = self._store.search(
                session,
                owner_id=owner_id,
                query_vector=query_vector,
                limit=limit,
                source=source,
                document_version=document_version,
            )
        return [result for result in results if result.score >= min_score]
