from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from knowledge.document_lifecycle import DocumentLifecycle, DocumentState
from storage.models import Base


def make_service():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, DocumentLifecycle(lambda: Session(engine, expire_on_commit=False))


def test_same_version_same_content_is_idempotent():
    engine, service = make_service()
    first = service.start_upload(owner_id=1, source="guide.md", version="v1", content="abc")
    second = service.start_upload(owner_id=1, source="guide.md", version="v1", content="abc")

    assert first.id == second.id
    assert second.state == DocumentState.PENDING


def test_same_version_different_content_is_rejected():
    engine, service = make_service()
    service.start_upload(owner_id=1, source="guide.md", version="v1", content="abc")

    with pytest.raises(ValueError, match="内容冲突"):
        service.start_upload(owner_id=1, source="guide.md", version="v1", content="changed")


def test_failed_new_version_keeps_old_active_version():
    engine, service = make_service()
    old = service.start_upload(owner_id=1, source="guide.md", version="v1", content="old")
    service.mark_processing(old.id)
    service.activate(old.id)
    new = service.start_upload(owner_id=1, source="guide.md", version="v2", content="new")
    service.mark_processing(new.id)
    service.mark_failed(new.id, "embedding failed")

    active = service.active_version(owner_id=1, source="guide.md")
    assert active == "v1"
    assert service.get(new.id).state == DocumentState.FAILED


def test_only_ready_active_document_is_queryable():
    engine, service = make_service()
    pending = service.start_upload(owner_id=1, source="guide.md", version="v1", content="abc")

    assert service.is_queryable(pending.id) is False
    service.mark_processing(pending.id)
    service.activate(pending.id)
    assert service.is_queryable(pending.id) is True
