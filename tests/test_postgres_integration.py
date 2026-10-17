import os

import pytest
from sqlalchemy.engine import make_url

from storage.database import Database
from storage.migration import upgrade_database
from storage.models import Base, User
from tasks.repository import TaskRepository


def test_postgres_repository_round_trip():
    raw_url = os.environ.get("TEST_DATABASE_URL")
    if raw_url is None:
        pytest.skip("需要 TEST_DATABASE_URL")
    if make_url(raw_url).database != "study_tasks_test":
        pytest.fail("TEST_DATABASE_URL 必须使用 study_tasks_test")

    database = Database(raw_url)
    Base.metadata.drop_all(database.engine)
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
        Base.metadata.drop_all(database.engine)
        with database.engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
        database.dispose()
