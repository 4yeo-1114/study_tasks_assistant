import re
from dataclasses import dataclass


_WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_]*|[0-9]+")
_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]+")


@dataclass(frozen=True)
class DocumentChunk:
    source: str
    chunk_id: int
    text: str

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("source 不能为空")
        if self.chunk_id < 1:
            raise ValueError("chunk_id 必须为正整数")
        if not self.text.strip():
            raise ValueError("text 不能为空")


@dataclass(frozen=True)
class SearchResult:
    chunk: DocumentChunk
    score: int


def tokenize(text: str) -> set[str]:
    """Extract simple English words and non-overlapping Chinese bigrams."""
    tokens = {match.group(0).lower() for match in _WORD_PATTERN.finditer(text)}
    for match in _CJK_PATTERN.finditer(text):
        run = match.group(0)
        tokens.update(run[index:index + 2] for index in range(0, len(run) - 1, 2))
    return tokens


class KeywordRetriever:
    def __init__(self, chunks: list[DocumentChunk]) -> None:
        self._chunks = tuple(chunks)

    #根据问题检索
    def search(
        self,
        query: str,
        *,
        limit: int = 3,
        min_score: int = 1,
    ) -> list[SearchResult]:
        if not query.strip():
            raise ValueError("问题不能为空")
        if limit < 1:
            raise ValueError("limit 必须大于 0")
        if min_score < 1:
            raise ValueError("min_score必须大于0")
        #对问题进行tokenize
        query_terms = tokenize(query)
        matches = []
        for position, chunk in enumerate(self._chunks):
            score = len(query_terms & tokenize(chunk.text))
            if score >= min_score:
                matches.append((score, position, SearchResult(chunk, score)))
        matches.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in matches[:limit]]


def build_context(results: list[SearchResult] | list[DocumentChunk]) -> str:
    if not results:
        return "没有找到与问题直接相关的资料，不能仅凭资料库给出答案。"

    lines = []
    for item in results:
        # Keyword and vector retrievers both expose ``.chunk``; keep the
        # context builder independent of the concrete score/result class.
        chunk = item.chunk if hasattr(item, "chunk") else item
        lines.append(f"[来源: {chunk.source}#{chunk.chunk_id}]\n{chunk.text}")
    return "\n\n".join(lines)
