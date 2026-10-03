from collections.abc import Sequence
from dataclasses import dataclass
from math import sqrt
from pathlib import Path
from typing import Protocol
import json

from rag import DocumentChunk


class EmbeddingModel(Protocol):
    def encode(self, text: str) -> Sequence[float]:
        """Encode text into one fixed-dimensional vector."""


class FastEmbedEmbeddingModel:
    """Real local ONNX embedding adapter without the PyTorch runtime."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-zh-v1.5",
        threads: int = 1,
        cache_dir: str | Path | None = None,
    ) -> None:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise RuntimeError(
                "请先安装 fastembed：python -m pip install fastembed"
            ) from exc
        if threads < 1:
            raise ValueError("threads 必须大于 0")
        self.model_name = model_name
        options = {"model_name": model_name, "threads": threads}
        if cache_dir is not None:
            options["cache_dir"] = str(cache_dir)
        self._model = TextEmbedding(**options)

    def encode(self, text: str) -> Sequence[float]:
        if not text.strip():
            raise ValueError("待编码文本不能为空")
        vector = next(self._model.embed([text]))
        return vector.tolist()


class SentenceTransformerEmbeddingModel:
    """Real local embedding model adapter backed by sentence-transformers."""

    def __init__(
        self,
        model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "请先安装 sentence-transformers：python -m pip install sentence-transformers"
            ) from exc
        self.model_name = model_name
        self._model = SentenceTransformer(model_name)

    def encode(self, text: str) -> Sequence[float]:
        if not text.strip():
            raise ValueError("待编码文本不能为空")
        vector = self._model.encode(
            text,
            convert_to_numpy=True,
            normalize_embeddings=False,
        )
        return vector.tolist()


@dataclass(frozen=True)
class EmbeddedChunk:
    chunk: DocumentChunk
    vector: tuple[float, ...]


@dataclass(frozen=True)
class VectorSearchResult:
    chunk: DocumentChunk
    score: float


@dataclass(frozen=True)
class VectorIndex:
    model_name: str
    dimension: int
    chunks: tuple[EmbeddedChunk, ...]

    def save(self, path: str | Path) -> None:
        payload = {
            "model_name": self.model_name,
            "dimension": self.dimension,
            "chunks": [
                {
                    "source": item.chunk.source,
                    "chunk_id": item.chunk.chunk_id,
                    "text": item.chunk.text,
                    "vector": list(item.vector),
                }
                for item in self.chunks
            ],
        }
        Path(path).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> "VectorIndex":
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            model_name = payload["model_name"]
            dimension = payload["dimension"]
            raw_chunks = payload["chunks"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValueError("向量索引文件格式不合法") from exc

        if not isinstance(model_name, str) or not model_name.strip():
            raise ValueError("索引缺少合法的 model_name")
        if not isinstance(dimension, int) or dimension < 1:
            raise ValueError("索引缺少合法的 dimension")
        if not isinstance(raw_chunks, list):
            raise ValueError("索引缺少合法的 chunks")

        chunks: list[EmbeddedChunk] = []
        for raw in raw_chunks:
            try:
                chunk = DocumentChunk(
                    source=raw["source"],
                    chunk_id=raw["chunk_id"],
                    text=raw["text"],
                )
                vector = tuple(float(value) for value in raw["vector"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("索引中的 chunk 格式不合法") from exc
            if len(vector) != dimension:
                raise ValueError("索引中的向量维度不一致")
            chunks.append(EmbeddedChunk(chunk, vector))
        return cls(model_name, dimension, tuple(chunks))


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right:
        raise ValueError("向量不能为空")
    if len(left) != len(right):
        raise ValueError("向量维度必须一致")

    dot = sum(a * b for a, b in zip(left, right))
    left_norm = sqrt(sum(value * value for value in left))
    right_norm = sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("零向量没有定义余弦相似度")
    return dot / (left_norm * right_norm)


class VectorRetriever:
    def __init__(
        self,
        chunks: Sequence[DocumentChunk],
        model: EmbeddingModel,
    ) -> None:
        self._model = model
        embedded: list[EmbeddedChunk] = []
        expected_dimension: int | None = None
        for chunk in chunks:
            vector = tuple(float(value) for value in model.encode(chunk.text))
            if not vector:
                raise ValueError("embedding 向量不能为空")
            if expected_dimension is None:
                expected_dimension = len(vector)
            elif len(vector) != expected_dimension:
                raise ValueError("文档向量维度必须一致")
            embedded.append(EmbeddedChunk(chunk, vector))
        self._embedded_chunks = tuple(embedded)
        self._model_name = getattr(model, "model_name", model.__class__.__name__)

    @property
    def index(self) -> VectorIndex:
        dimension = len(self._embedded_chunks[0].vector) if self._embedded_chunks else 0
        if dimension == 0:
            raise ValueError("空索引没有向量维度")
        return VectorIndex(self._model_name, dimension, self._embedded_chunks)

    @classmethod
    def from_index(cls, index: VectorIndex, model: EmbeddingModel) -> "VectorRetriever":
        model_name = getattr(model, "model_name", model.__class__.__name__)
        if model_name != index.model_name:
            raise ValueError("查询模型与索引模型不一致，必须重建索引")
        instance = cls.__new__(cls)
        instance._model = model
        instance._model_name = model_name
        instance._embedded_chunks = index.chunks
        return instance

    def search(
        self,
        query: str,
        *,
        limit: int = 3,
        min_score: float = -1.0,
    ) -> list[VectorSearchResult]:
        if not query.strip():
            raise ValueError("问题不能为空")
        if limit < 1:
            raise ValueError("limit 必须大于 0")
        if not -1 <= min_score <= 1:
            raise ValueError("min_score 必须在 -1 到 1 之间")

        query_vector = self._validated_vector(self._model.encode(query))
        matches = [
            VectorSearchResult(
                item.chunk,
                cosine_similarity(query_vector, item.vector),
            )
            for item in self._embedded_chunks
        ]
        matches = [item for item in matches if item.score >= min_score]
        matches.sort(key=lambda item: (-item.score, item.chunk.source, item.chunk.chunk_id))
        return matches[:limit]

    def _validated_vector(self, vector: Sequence[float]) -> tuple[float, ...]:
        values = tuple(float(value) for value in vector)
        if not values:
            raise ValueError("embedding 向量不能为空")
        if hasattr(self, "_embedded_chunks") and self._embedded_chunks:
            expected = len(self._embedded_chunks[0].vector)
            if len(values) != expected:
                raise ValueError("查询向量与文档向量维度不一致")
        return values
