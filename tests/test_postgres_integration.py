import os

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from storage.database import Database
from storage.migration import upgrade_database
from storage.models import Base, User
from tasks.repository import TaskRepository
from knowledge.keyword_retrieval import PgKeywordRetriever
from knowledge.rag import tokenize


def test_postgres_repository_round_trip():
    raw_url = os.environ.get("TEST_DATABASE_URL")
    if raw_url is None:
        pytest.skip("需要 TEST_DATABASE_URL")
    if make_url(raw_url).database != "study_tasks_test":
        pytest.fail("TEST_DATABASE_URL 必须使用 study_tasks_test")

    database = Database(raw_url)
    _reset_database(database)
    with database.engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
    upgrade_database(raw_url)
    try:
        repository = TaskRepository(database.sessions)
        with database.sessions.begin() as session:
            user = User(username="pg_test", password_hash="unused-in-repository-test")
            other = User(username="pg_other", password_hash="unused-in-repository-test")
            session.add(user)
            session.add(other)
            session.flush()
            user_id = user.id
            other_id = other.id
        created = repository.create_task(
            user_id=user_id,
            title="PostgreSQL 集成测试",
            priority="medium",
            due_date=None,
        )
        assert repository.get_task(user_id, created["id"]) == created
        assert repository.list_tasks(other_id) == []
        assert repository.get_task(other_id, created["id"]) is None
        assert repository.update_task_status(other_id, created["id"], "completed") is None
        assert repository.delete_task(other_id, created["id"]) is False
        assert repository.get_task(user_id, created["id"]) == created
    finally:
        _reset_database(database)
        database.dispose()


def test_postgres_upg03_full_text_columns_and_page_provenance():
    raw_url = os.environ.get("TEST_DATABASE_URL")
    if raw_url is None:
        pytest.skip("需要 TEST_DATABASE_URL")
    if make_url(raw_url).database != "study_tasks_test":
        pytest.fail("TEST_DATABASE_URL 必须使用 study_tasks_test")

    database = Database(raw_url)
    _reset_database(database)
    with database.engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
    upgrade_database(raw_url)
    try:
        with database.sessions.begin() as session:
            user = User(username="fts_test", password_hash="unused")
            session.add(user)
            session.flush()
            content = "\u4e8b\u52a1\u8fb9\u754c\u4e0e\u6743\u9650\u6821\u9a8c"
            search_tokens = " ".join(sorted(tokenize(content)))
            session.execute(
                text(
                    """
                    INSERT INTO documents
                    (id, owner_id, source, document_version, content_hash, state,
                     active_version, created_at, updated_at)
                    VALUES ('fts-doc', :owner_id, 'guide.pdf', 'v1', 'hash', 'ready',
                            'v1', now(), now())
                    """
                ),
                {"owner_id": user.id},
            )
            session.execute(
                text(
                    """
                    INSERT INTO document_chunks
                    (owner_id, source, chunk_id, content, embedding,
                     embedding_model, embedding_dimension, document_version,
                     page_number, search_tokens)
                    VALUES (:owner_id, 'guide.pdf', 1, :content,
                            CAST(:embedding AS vector), 'test', 512, 'v1', 3,
                            :search_tokens)
                    """
                ),
                {
                    "owner_id": user.id,
                    "content": content,
                    "search_tokens": search_tokens,
                    "embedding": "[" + ",".join(["0"] * 512) + "]",
                },
            )
        results = PgKeywordRetriever(database.sessions).search(
            "\u6743\u9650\u6821\u9a8c\u65e0\u5173\u8bcd", owner_id=user.id, limit=3
        )
        assert len(results) == 1
        assert results[0].chunk.page_number == 3
    finally:
        _reset_database(database)
        database.dispose()


def _reset_database(database):
    """Reset the integration database including legacy raw-SQL tables."""
    if database.engine.dialect.name == "postgresql":
        with database.engine.begin() as connection:
            connection.exec_driver_sql("DROP SCHEMA public CASCADE")
            connection.exec_driver_sql("CREATE SCHEMA public")
    else:
        Base.metadata.drop_all(database.engine)
        with database.engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
