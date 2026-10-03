from dataclasses import dataclass

from embedding_retrieval import EmbeddingModel
from pgvector_store import PgVectorStore
from rag import DocumentChunk


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


def ingest_document(
    sessions,
    store: PgVectorStore,
    model: EmbeddingModel,
    *,
    owner_id: int,
    source: str,
    text: str,
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
        chunks = chunk_text(
            text,
            source=source,
            chunk_size=config.chunk_size,
            overlap=config.overlap,
        )
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
            for chunk in chunks:
                store.insert_chunk(
                    session,
                    owner_id=owner_id,
                    chunk=chunk,
                    vector=model.encode(chunk.text),
                    document_version=config.document_version,
                )
        if lifecycle is not None:
            lifecycle.activate(document.id)
        return len(chunks)
    except Exception as exc:
        if lifecycle is not None:
            lifecycle.mark_failed(document.id, str(exc) or type(exc).__name__)
        raise
