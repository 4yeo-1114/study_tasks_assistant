from types import SimpleNamespace
import json
import logging

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from knowledge.document_service import (
    DocumentNotFoundError,
    DocumentService,
    DocumentUpload,
)
from storage.models import Base
from knowledge.document_lifecycle import DocumentVersionConflictError
from core.observability import request_context


class FakeModel:
    model_name = "test-model"

    def encode(self, text):
        return [float(len(text)), 1.0]


class FakeStore:
    def __init__(self):
        self.inserted = []
        self.deleted = []

    def insert_chunk(self, session, *, owner_id, chunk, vector, document_version):
        self.inserted.append((owner_id, chunk, tuple(vector), document_version))

    def delete_document_version(self, session, *, owner_id, source, document_version):
        self.deleted.append((owner_id, source, document_version))
        return 1


@pytest.fixture
def document_service():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    store = FakeStore()
    service = DocumentService(sessions, store, FakeModel())
    yield service, store
    engine.dispose()


def upload(version="v1", content="Agent 工具调用必须使用服务端 owner_id"):
    return DocumentUpload(
        source="agent.md",
        content=content,
        document_version=version,
        chunk_size=100,
        overlap=10,
    )


def test_ingest_is_idempotent_for_same_content_and_lists_owner_documents(document_service):
    service, store = document_service

    first = service.ingest(1, upload())
    second = service.ingest(1, upload())

    assert first.chunks_ingested == 1
    assert second.chunks_ingested == 0
    assert first.document.state == "ready"
    assert [item.id for item in service.list(1)] == [first.document.id]
    assert service.list(2) == []
    assert len(store.inserted) == 1


def test_same_version_with_different_content_is_a_conflict(document_service):
    service, _ = document_service
    service.ingest(1, upload(content="first"))

    with pytest.raises(DocumentVersionConflictError):
        service.ingest(1, upload(content="different"))


def test_get_and_delete_are_owner_scoped(document_service):
    service, store = document_service
    result = service.ingest(1, upload())
    store.deleted.clear()

    with pytest.raises(DocumentNotFoundError):
        service.get(2, result.document.id)
    with pytest.raises(DocumentNotFoundError):
        service.delete(2, result.document.id)

    deleted = service.delete(1, result.document.id)

    assert deleted.state == "deleted"
    assert store.deleted == [(1, "agent.md", "v1")]


def test_ingestion_logs_metadata_without_document_content(document_service, caplog):
    service, _ = document_service
    private_content = "private document body"

    with request_context("http-document"):
        with caplog.at_level(logging.INFO, logger="study_task.document"):
            result = service.ingest(1, upload(content=private_content))
            with pytest.raises(DocumentVersionConflictError):
                service.ingest(1, upload(content="different private body"))

    events = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "study_task.document"
    ]
    completed = next(event for event in events if event["event"] == "document_ingestion_completed")
    failed = next(event for event in events if event["event"] == "document_ingestion_failed")
    assert completed["request_id"] == "http-document"
    assert completed["document_id"] == result.document.id
    assert completed["state"] == "ready"
    assert completed["chunks_ingested"] == 1
    assert completed["duration_ms"] >= 0
    assert failed["error_type"] == "DocumentVersionConflictError"
    assert private_content not in caplog.text
    assert "different private body" not in caplog.text
