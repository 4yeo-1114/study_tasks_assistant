from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from document_lifecycle import DocumentLifecycle, DocumentState
from models import Base, Document


class Store:
    def __init__(self):
        self.deleted = []

    def delete_document_version(self, session, *, owner_id, source, document_version):
        self.deleted.append((owner_id, source, document_version))
        return 2


def setup():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = lambda: Session(engine, expire_on_commit=False)
    return engine, DocumentLifecycle(sessions), sessions


def test_delete_marks_document_deleted_and_removes_only_its_chunks():
    engine, lifecycle, sessions = setup()
    document = lifecycle.start_upload(owner_id=1, source="guide.md", version="v1", content="abc")
    lifecycle.mark_processing(document.id)
    lifecycle.activate(document.id)
    store = Store()

    deleted = lifecycle.delete(document.id, store)

    assert deleted.state == DocumentState.DELETED
    assert deleted.active_version is None
    assert store.deleted == [(1, "guide.md", "v1")]
    with sessions() as session:
        saved = session.get(Document, document.id)
        assert saved.state == DocumentState.DELETED


def test_activate_rejects_a_target_that_is_no_longer_processing():
    engine, lifecycle, sessions = setup()
    document = lifecycle.start_upload(owner_id=1, source="guide.md", version="v1", content="abc")
    lifecycle.mark_processing(document.id)
    lifecycle.activate(document.id)

    try:
        lifecycle.activate(document.id)
    except ValueError as exc:
        assert "processing" in str(exc)
    else:
        raise AssertionError("重复激活必须失败")
