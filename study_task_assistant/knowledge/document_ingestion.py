from dataclasses import dataclass
import re

from knowledge.embedding_retrieval import EmbeddingModel
from storage.pgvector_store import PgVectorStore
from knowledge.rag import DocumentChunk


@dataclass(frozen=True)
class IngestionConfig:
    chunk_size: int = 500
    overlap: int = 50
    document_version: str = "v1"

    def __post_init__(self) -> None:
        if self.chunk_size < 1:
            raise ValueError("chunk_size 必须大于 0")
        if self.overlap < 0 or self.overlap >= self.chunk_size:
            raise ValueError("overlap 必须大于等于 0 且小于 chunk_size")
        if not self.document_version.strip():
            raise ValueError("document_version 不能为空")


@dataclass(frozen=True)
class ParsedPage:
    page_number: int
    text: str

    def __post_init__(self) -> None:
        if self.page_number < 1:
            raise ValueError("page_number 必须从 1 开始")


def chunk_text(
    text: str,
    *,
    source: str,
    chunk_size: int = 500,
    overlap: int = 50,
) -> list[DocumentChunk]:
    config = IngestionConfig(chunk_size, overlap)
    if not text.strip():
        raise ValueError("文档内容不能为空")
    chunks: list[DocumentChunk] = []
    step = config.chunk_size - config.overlap
    for position, start in enumerate(range(0, len(text), step), start=1):
        content = text[start : start + config.chunk_size]
        if content:
            chunks.append(DocumentChunk(source, position, content))
        if start + config.chunk_size >= len(text):
            break
    return chunks


def chunk_pages(
    pages: list[ParsedPage],
    *,
    source: str,
    chunk_size: int = 500,
    overlap: int = 50,
) -> list[DocumentChunk]:
    """Chunk page text without crossing page boundaries or paragraph boundaries."""
    config = IngestionConfig(chunk_size, overlap)
    chunks: list[DocumentChunk] = []
    for page in pages:
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", page.text) if part.strip()]
        if not paragraphs:
            continue
        for paragraph in paragraphs:
            if len(paragraph) <= config.chunk_size:
                chunks.append(DocumentChunk(source, len(chunks) + 1, paragraph, page.page_number))
                continue
            for item in chunk_text(
                paragraph,
                source=source,
                chunk_size=config.chunk_size,
                overlap=config.overlap,
            ):
                chunks.append(DocumentChunk(source, len(chunks) + 1, item.text, page.page_number))
    if not chunks:
        raise ValueError("文档内容不能为空")
    return chunks


def ingest_document(
    sessions,
    store: PgVectorStore,
    model: EmbeddingModel,
    *,
    owner_id: int,
    source: str,
    text: str,
    pages: tuple[ParsedPage, ...] | None = None,
    config: IngestionConfig = IngestionConfig(),
    replace_existing: bool = True,
    lifecycle=None,
) -> int:
    """Chunk, encode and persist one document in one database transaction."""
    document = None
    if lifecycle is not None:
        document = lifecycle.start_upload(
            owner_id=owner_id,
            source=source,
            version=config.document_version,
            content=text,
        )
        #若上传重复版本 直接返回
        if document.state == "ready":
            return 0
        lifecycle.mark_processing(document.id)

    try:
        chunks = chunk_pages(
            list(pages) if pages is not None else [ParsedPage(1, text)],
            source=source,
            chunk_size=config.chunk_size,
            overlap=config.overlap,
        )
        vectors = _encode_many(model, [chunk.text for chunk in chunks])
        if hasattr(sessions, "begin"):
            transaction_context = sessions.begin()
        else:
            session = sessions()
            transaction_context = session.begin()
        with transaction_context as session:
            if replace_existing:
                if lifecycle is None:
                    store.delete_document(session,
                                          owner_id=owner_id,
                                          source=source)
                else:
                    store.delete_document_version(
                        session,
                        owner_id=owner_id,
                        source=source,
                        document_version=config.document_version,
                    )
            for chunk, vector in zip(chunks, vectors):
                store.insert_chunk(
                    session,
                    owner_id=owner_id,
                    chunk=chunk,
                    vector=vector,
                    document_version=config.document_version,
                )
        if lifecycle is not None:
            lifecycle.activate(document.id)
        return len(chunks)
    except Exception as exc:
        if lifecycle is not None:
            lifecycle.mark_failed(document.id, str(exc) or type(exc).__name__)
        raise


def _encode_many(model: EmbeddingModel, texts: list[str]) -> list[tuple[float, ...]]:
    batch_encoder = getattr(model, "encode_many", None)
    raw_vectors = batch_encoder(texts) if callable(batch_encoder) else [model.encode(text) for text in texts]
    vectors = [tuple(float(value) for value in vector) for vector in raw_vectors]
    if len(vectors) != len(texts):
        raise ValueError("embedding 返回数量与分块数量不一致")
    return vectors
