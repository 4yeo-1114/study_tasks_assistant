from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import pytest

from knowledge.document_ingestion import IngestionConfig, ingest_document
from knowledge.document_lifecycle import DocumentLifecycle, DocumentState
from storage.models import Base
from knowledge.rag import DocumentChunk


class Model:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    def encode(self, text):
        self.calls += 1
        if self.fail and self.calls == 2:
            raise RuntimeError("embedding failed")
        return [1.0, 0.0]


class Store:
    def __init__(self):
        self.deleted = []
        self.inserted = []

    def delete_document(self, session, *, owner_id, source):
        self.deleted.append((owner_id, source))
        return 0

    def delete_document_version(self, session, *, owner_id, source, document_version):
        self.deleted.append((owner_id, source, document_version))
        return 0

    def insert_chunk(self, session, *, owner_id, chunk, vector, document_version):
        self.inserted.append((owner_id, chunk, document_version))


class TransactionProbeStore(Store):
    def __init__(self, sessions):
        super().__init__()
        self.sessions = sessions

    def insert_chunk(self, session, *, owner_id, chunk, vector, document_version):
        assert self.sessions.begin_called is True
        super().insert_chunk(session, owner_id=owner_id, chunk=chunk, vector=vector, document_version=document_version)


def setup():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = lambda: Session(engine, expire_on_commit=False)
    return engine, sessions, DocumentLifecycle(sessions), Store()


def test_failed_new_ingestion_keeps_previous_active_version():
    engine, sessions, lifecycle, store = setup()
    ingest_document(
        sessions,
        store,
        Model(),
        owner_id=1,
        source="guide.md",
        text="old document",
        config=IngestionConfig(chunk_size=5, overlap=0, document_version="v1"),
        lifecycle=lifecycle,
    )

    with pytest.raises(RuntimeError, match="embedding failed"):
        ingest_document(
            sessions,
            store,
            Model(fail=True),
            owner_id=1,
            source="guide.md",
            text="new document content",
            config=IngestionConfig(chunk_size=5, overlap=0, document_version="v2"),
            lifecycle=lifecycle,
        )

    assert lifecycle.active_version(owner_id=1, source="guide.md") == "v1"


def test_ready_version_is_idempotent_and_skips_reembedding():
    engine, sessions, lifecycle, store = setup()
    first_model = Model()
    config = IngestionConfig(chunk_size=5, overlap=0, document_version="v1")
    ingest_document(
        sessions, store, first_model, owner_id=1, source="guide.md", text="same", config=config, lifecycle=lifecycle
    )
    second_model = Model()
    count = ingest_document(
        sessions, store, second_model, owner_id=1, source="guide.md", text="same", config=config, lifecycle=lifecycle
    )

    assert count == 0
    assert second_model.calls == 0


def test_embeddings_are_generated_before_write_transaction():
    class Sessions:
        begin_called = False

        def begin(self):
            Sessions.begin_called = True
            return self

        def __enter__(self):
            return object()

        def __exit__(self, *args):
            return False

    sessions = Sessions()
    store = TransactionProbeStore(sessions)
    ingest_document(
        sessions,
        store,
        Model(),
        owner_id=1,
        source="guide.md",
        text="abcdefghij",
        config=IngestionConfig(chunk_size=5, overlap=0),
    )
    assert len(store.inserted) == 2


def test_ingestion_uses_batch_encoder_when_available():
    class BatchModel(Model):
        def __init__(self):
            super().__init__()
            self.batch_calls = []

        def encode_many(self, texts):
            self.batch_calls.append(list(texts))
            return [[1.0, 0.0] for _ in texts]

    model = BatchModel()
    store = Store()
    ingest_document(
        lambda: Session(create_engine("sqlite+pysqlite:///:memory:")),
        store,
        model,
        owner_id=1,
        source="guide.md",
        text="abcdefghij",
        config=IngestionConfig(chunk_size=5, overlap=0),
    )
    assert len(model.batch_calls) == 1
    assert len(model.batch_calls[0]) == 2
