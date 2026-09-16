import os

import pytest
from sqlalchemy.engine import make_url

from database import Database
from migration import upgrade_database
from models import Base
from repository import TaskRepository


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
        created = repository.create_task(
            title="PostgreSQL 集成测试",
            priority="medium",
            due_date=None,
        )
        assert repository.get_task(created["id"]) == created
    finally:
        Base.metadata.drop_all(database.engine)
        with database.engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
        database.dispose()
