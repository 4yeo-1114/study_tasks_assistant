from dataclasses import dataclass
import inspect
from typing import Any, Protocol, Sequence

from knowledge.rag import DocumentChunk


class Retriever(Protocol):
    def search(self, query: str, *, limit: int = 3) -> Sequence[Any]:
        """Return objects exposing ``chunk`` and optionally ``score``."""

#统一过滤契约
@dataclass(frozen=True)
class RetrievalFilters:
    """Server-controlled scope shared by every retrieval strategy."""

    owner_id: int
    source: str | None = None
    document_version: str | None = None

    def __post_init__(self) -> None:
        if self.owner_id < 1:
            raise ValueError("owner_id 必须为正整数")
        if self.source is not None and not self.source.strip():
            raise ValueError("source 不能为空")
        if self.document_version is not None and not self.document_version.strip():
            raise ValueError("document_version 不能为空")


@dataclass(frozen=True)
class RetrievalCandidate:
    """One unique chunk after keyword/vector rank fusion."""

    chunk: DocumentChunk
    fused_score: float
    keyword_rank: int | None
    vector_rank: int | None
    keyword_score: float | None
    vector_score: float | None


class HybridRetriever:
    """Combine keyword and vector retrieval with Reciprocal Rank Fusion."""

    def __init__(
        self,
        keyword_retriever: Retriever,
        vector_retriever: Retriever,
        *,
        rrf_k: int = 60,
    ) -> None:
        if rrf_k < 1:
            raise ValueError("rrf_k 必须大于 0")
        self._keyword = keyword_retriever
        self._vector = vector_retriever
        self._rrf_k = rrf_k

    def search(
        self,
        query: str,
        *,
        #混合检索的输出数topk
        limit: int = 3,
        #candidate_limit表示的是每一侧的候选数量
        candidate_limit: int | None = None,
        filters: RetrievalFilters | None = None,
    ) -> list[RetrievalCandidate]:
        if not query.strip():
            raise ValueError("问题不能为空")
        if limit < 1:
            raise ValueError("limit 必须大于 0")
        if candidate_limit is not None and candidate_limit < 1:
            raise ValueError("candidate_limit 必须大于 0")

        requested_limit = max(limit, candidate_limit or limit * 3)
        keyword_results = list(
            self._search_side(self._keyword, query, requested_limit, filters)
        )
        vector_results = list(
            self._search_side(self._vector, query, requested_limit, filters)
        )
        merged: dict[tuple[str, int], dict[str, Any]] = {}

        for rank, result in enumerate(keyword_results, start=1):
            self._merge_result(merged, result, rank, side="keyword")
        for rank, result in enumerate(vector_results, start=1):
            self._merge_result(merged, result, rank, side="vector")

        candidates = [
            RetrievalCandidate(
                chunk=item["chunk"],
                fused_score=item["fused_score"],
                keyword_rank=item.get("keyword_rank"),
                vector_rank=item.get("vector_rank"),
                keyword_score=item.get("keyword_score"),
                vector_score=item.get("vector_score"),
            )
            for item in merged.values()
        ]
        candidates.sort(
            key=lambda item: (
                -item.fused_score,
                item.chunk.source,
                item.chunk.chunk_id,
            )
        )
        return candidates[:limit]

    @staticmethod
    def _search_side(
        retriever: Retriever,
        query: str,
        limit: int,
        filters: RetrievalFilters | None,
    ) -> Sequence[Any]:
        if filters is None:
            return retriever.search(query, limit=limit)

        parameters = inspect.signature(retriever.search).parameters
        required = ("owner_id", "source", "document_version")
        missing = [name for name in required if name not in parameters]
        if missing:
            raise TypeError(
                "检索器不支持统一过滤契约，缺少: " + ", ".join(missing)
            )
        return retriever.search(
            query,
            limit=limit,
            owner_id=filters.owner_id,
            source=filters.source,
            document_version=filters.document_version,
        )

    def _merge_result(
        self,
        merged: dict[tuple[str, int], dict[str, Any]],
        result: Any,
        rank: int,
        *,
        side: str,
    ) -> None:
        chunk = getattr(result, "chunk", None)
        if not isinstance(chunk, DocumentChunk):
            raise TypeError("检索结果必须包含 DocumentChunk 类型的 chunk")
        key = (chunk.source, chunk.chunk_id)
        item = merged.setdefault(
            key,
            {
                "chunk": chunk,
                "fused_score": 0.0,
            },
        )
        item["fused_score"] += 1.0 / (self._rrf_k + rank)
        item[f"{side}_rank"] = rank
        score = getattr(result, "score", None)
        item[f"{side}_score"] = float(score) if score is not None else None


# dict.setdefault(key, default)：
# 如果 key 不在 merged 字典中，则插入该键并设为默认字典 {...}，同时返回该默认字典。
# 如果 key 已经存在，则直接返回已有值，不做任何覆盖。
# item 拿到的是merge[key]下那个子字典的引用，后续对 item 的修改会直接同步更新。
