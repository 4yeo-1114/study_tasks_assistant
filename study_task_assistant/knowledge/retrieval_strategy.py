from collections.abc import Iterable

from knowledge.rag import KeywordRetriever, SearchResult

#加入扩展词
def expand_query(query: str, expansions: Iterable[str] = ()) -> tuple[str, ...]:
    """Return the original query plus bounded, caller-approved search variants."""
    if not query.strip():
        raise ValueError("问题不能为空")
    values = [query.strip()]
    for item in expansions:
        value = item.strip()
        if value and value not in values:
            values.append(value)
    return tuple(values)


def search_with_expansion(
    retriever: KeywordRetriever,
    query: str,
    *,
    expansions: Iterable[str] = (),
    limit: int = 3,
) -> list[SearchResult]:
    """Search several query forms, deduplicate chunks, then keep the best scores."""
    if limit < 1:
        raise ValueError("limit 必须大于 0")

    best_by_chunk: dict[tuple[str, int], SearchResult] = {}
    for variant in expand_query(query, expansions):
        for result in retriever.search(variant, limit=limit):
            key = (result.chunk.source, result.chunk.chunk_id)
            previous = best_by_chunk.get(key)
            #虽然每个chunk的source和id元组是独一无二的 但是searchresult的分数会不一样
            if previous is None or result.score > previous.score:
                best_by_chunk[key] = result

    return sorted(
        best_by_chunk.values(),
        key=lambda result: (-result.score, result.chunk.source, result.chunk.chunk_id),
    )[:limit]
