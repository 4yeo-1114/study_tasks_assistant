from dataclasses import dataclass
from typing import Any, Sequence

from sqlalchemy import text

from knowledge.hybrid_retrieval import RetrievalFilters
from knowledge.rag import DocumentChunk, SearchResult, tokenize


@dataclass(frozen=True)
class KeywordIndexedChunk:
    """A keyword-index record carrying the same scope metadata as pgvector."""

    owner_id: int
    document_version: str
    chunk: DocumentChunk

    def __post_init__(self) -> None:
        if self.owner_id < 1:
            raise ValueError("owner_id 必须为正整数")
        if not self.document_version.strip():
            raise ValueError("document_version 不能为空")


class ScopedKeywordRetriever:
    """Keyword retrieval that enforces owner/version/source filters before scoring."""

    def __init__(self, records: Sequence[KeywordIndexedChunk]) -> None:
        self._records = tuple(records)

    def search(
        self,
        query: str,
        *,
        owner_id: int,
        limit: int = 3,
        min_score: int = 1,
        source: str | None = None,
        document_version: str | None = None,
    ) -> list[SearchResult]:
        filters = RetrievalFilters(
            owner_id=owner_id,
            source=source,
            document_version=document_version,
        )
        if not query.strip():
            raise ValueError("问题不能为空")
        if limit < 1:
            raise ValueError("limit 必须大于 0")
        if min_score < 1:
            raise ValueError("min_score 必须大于 0")

        query_terms = tokenize(query)
        matches: list[tuple[int, int, SearchResult]] = []
        for position, record in enumerate(self._records):
            if record.owner_id != filters.owner_id:
                continue
            if filters.source is not None and record.chunk.source != filters.source:
                continue
            if (
                filters.document_version is not None
                and record.document_version != filters.document_version
            ):
                continue
            score = len(query_terms & tokenize(record.chunk.text))
            if score >= min_score:
                matches.append((score, position, SearchResult(record.chunk, score)))

        matches.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in matches[:limit]]


class PgKeywordRetriever:
    """Use PostgreSQL FTS to bound candidates, then apply deterministic scoring."""

    def __init__(self, sessions: Any) -> None:
        self._sessions = sessions

    def search(
        self,
        query: str,
        *,
        owner_id: int,
        limit: int = 3,
        min_score: int = 1,
        source: str | None = None,
        document_version: str | None = None,
    ) -> list[SearchResult]:
        filters = RetrievalFilters(
            owner_id=owner_id,
            source=source,
            document_version=document_version,
        )
        if not query.strip():
            raise ValueError("问题不能为空")
        if limit < 1:
            raise ValueError("limit 必须大于 0")
        if min_score < 1:
            raise ValueError("min_score 必须大于 0")

        conditions = [
            "document_chunks.owner_id = :owner_id",
            "documents.state = 'ready'",
            "documents.active_version = document_chunks.document_version",
        ]
        params: dict[str, object] = {"owner_id": filters.owner_id}
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        # The final score counts any shared token. Use OR here so the indexed
        # candidate filter cannot discard a chunk merely because it lacks an
        # unrelated query token; tokens come only from tokenize(), not raw SQL.
        params["fts_query"] = " | ".join(sorted(query_tokens))
        conditions.append("document_chunks.search_vector @@ to_tsquery('simple', :fts_query)")
        if filters.source is not None:
            conditions.append("document_chunks.source = :source")
            params["source"] = filters.source
        if filters.document_version is not None:
            conditions.append("document_chunks.document_version = :document_version")
            params["document_version"] = filters.document_version

        with self._sessions() as session:
            rows = session.execute(
                text(f"""
                SELECT document_chunks.source, document_chunks.chunk_id,
                       document_chunks.content, document_chunks.page_number,
                       ts_rank_cd(document_chunks.search_vector,
                                  to_tsquery('simple', :fts_query)) AS rank
                FROM document_chunks
                JOIN documents
                  ON documents.owner_id = document_chunks.owner_id
                 AND documents.source = document_chunks.source
                 AND documents.document_version = document_chunks.document_version
                WHERE {" AND ".join(conditions)}
                ORDER BY rank DESC, document_chunks.source, document_chunks.chunk_id
                LIMIT :candidate_limit
                """),
                {**params, "candidate_limit": max(limit * 4, limit)},
            )

            matches: list[tuple[int, int, SearchResult]] = []
            for position, row in enumerate(rows):
                chunk = DocumentChunk(row.source, row.chunk_id, row.content, getattr(row, "page_number", None))
                score = len(query_tokens & tokenize(chunk.text))
                if score >= min_score:
                    matches.append((score, position, SearchResult(chunk, score)))

        matches.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in matches[:limit]]
