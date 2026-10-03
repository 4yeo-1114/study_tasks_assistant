from dataclasses import dataclass
import logging
from time import perf_counter

from document_ingestion import IngestionConfig, ingest_document
from document_lifecycle import DocumentLifecycle
from embedding_retrieval import EmbeddingModel
from models import Document
from pgvector_store import PgVectorStore
from observability import log_event


logger = logging.getLogger("study_task.document")


class DocumentNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class DocumentUpload:
    source: str
    content: str
    document_version: str = "v1"
    chunk_size: int = 500
    overlap: int = 50


@dataclass(frozen=True)
class DocumentIngestResult:
    document: Document
    chunks_ingested: int


class DocumentService:
    def __init__(self, sessions, store: PgVectorStore, model: EmbeddingModel) -> None:
        self._sessions = sessions
        self._store = store
        self._model = model
        self._lifecycle = DocumentLifecycle(sessions)

    def ingest(self, owner_id: int, upload: DocumentUpload) -> DocumentIngestResult:
        started = perf_counter()
        try:
            chunks_ingested = ingest_document(
                self._sessions,
                self._store,
                self._model,
                owner_id=owner_id,
                source=upload.source,
                text=upload.content,
                config=IngestionConfig(
                    chunk_size=upload.chunk_size,
                    overlap=upload.overlap,
                    document_version=upload.document_version,
                ),
                lifecycle=self._lifecycle,
            )
            document = self._lifecycle.get_version(
                owner_id=owner_id,
                source=upload.source,
                version=upload.document_version,
            )
            if document is None:
                raise RuntimeError("文档写入完成后无法读取生命周期记录")
        except Exception as exc:
            log_event(
                logger,
                "document_ingestion_failed",
                level=logging.WARNING,
                duration_ms=(perf_counter() - started) * 1000,
                error_type=type(exc).__name__,
            )
            raise
        log_event(
            logger,
            "document_ingestion_completed",
            document_id=document.id,
            state=document.state,
            chunks_ingested=chunks_ingested,
            duration_ms=(perf_counter() - started) * 1000,
        )
        return DocumentIngestResult(document, chunks_ingested)

    def list(self, owner_id: int) -> list[Document]:
        return self._lifecycle.list_for_owner(owner_id)

    def get(self, owner_id: int, document_id: str) -> Document:
        document = self._lifecycle.get_for_owner(
            owner_id=owner_id,
            document_id=document_id,
        )
        if document is None:
            raise DocumentNotFoundError("文档不存在")
        return document

    def delete(self, owner_id: int, document_id: str) -> Document:
        try:
            return self._lifecycle.delete(
                document_id,
                self._store,
                owner_id=owner_id,
            )
        except KeyError as exc:
            raise DocumentNotFoundError("文档不存在") from exc
