from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from storage.migration import upgrade_database


def test_create_app_does_not_create_schema(tmp_path):
    from web.api import create_app

    url = f"sqlite+pysqlite:///{(tmp_path / 'unmigrated.db').as_posix()}"
    app = create_app(url)
    try:
        assert "tasks" not in inspect(app.state.database.engine).get_table_names()
    finally:
        app.state.database.dispose()


def test_upgrade_creates_versioned_tasks_table(tmp_path):
    url = f"sqlite+pysqlite:///{(tmp_path / 'fresh.db').as_posix()}"

    upgrade_database(url)

    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        assert "tasks" in inspector.get_table_names()
        assert "task_proposals" in inspector.get_table_names()
        assert {"user_profiles", "agent_sessions", "agent_runs", "agent_messages", "weekly_plans"}.issubset(
            inspector.get_table_names()
        )
        assert all(
            "task_id" not in fk["constrained_columns"]
            for fk in inspector.get_foreign_keys("task_proposals")
        )
        assert "alembic_version" in inspector.get_table_names()
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
                    ).scalar_one() == "0017_agent_message_sequence"
    finally:
        engine.dispose()


def test_upgrade_preserves_existing_tasks_without_assigning_owner(tmp_path):
    url = f"sqlite+pysqlite:///{(tmp_path / 'existing.db').as_posix()}"
    config = Config(str(Path(__file__).parents[1] / "study_task_assistant" / "alembic.ini"))
    config.attributes["database_url"] = url
    command.upgrade(config, "0001_initial_tasks")
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO tasks (id,title,status,priority) "
                "VALUES (7,'旧任务','pending','low')"
            ))
    finally:
        engine.dispose()

    upgrade_database(url)

    engine = create_engine(url)
    try:
        assert "users" in inspect(engine).get_table_names()
        assert "owner_id" in {c["name"] for c in inspect(engine).get_columns("tasks")}
        with engine.connect() as connection:
            assert connection.execute(text(
                "SELECT id,title,owner_id FROM tasks"
            )).fetchall() == [(7, "旧任务", None)]
    finally:
        engine.dispose()

    command.downgrade(config, "0001_initial_tasks")
    engine = create_engine(url)
    try:
        assert "users" not in inspect(engine).get_table_names()
        assert "owner_id" not in {
            column["name"] for column in inspect(engine).get_columns("tasks")
        }
        with engine.connect() as connection:
            assert connection.execute(text("SELECT id,title FROM tasks")).fetchall() == [
                (7, "旧任务")
            ]
    finally:
        engine.dispose()


def test_agent_message_sequence_migration_backfills_existing_messages(tmp_path):
    url = f"sqlite+pysqlite:///{(tmp_path / 'agent-sequence.db').as_posix()}"
    config = Config(str(Path(__file__).parents[1] / "study_task_assistant" / "alembic.ini"))
    config.attributes["database_url"] = url
    command.upgrade(config, "0016_plan_adjustments")
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO users (id,username,password_hash) VALUES (1,'sequence-owner','x')"
            ))
            connection.execute(text(
                "INSERT INTO agent_sessions (id,owner_id,status,created_at,updated_at) "
                "VALUES ('old-session',1,'active',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            ))
            connection.execute(text(
                "INSERT INTO agent_messages (session_id,sequence,role,content,created_at) "
                "VALUES ('old-session',4,'assistant','old',CURRENT_TIMESTAMP)"
            ))
    finally:
        engine.dispose()

    upgrade_database(url)
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text(
                "SELECT message_sequence FROM agent_sessions WHERE id='old-session'"
            )) == 4
            assert connection.scalar(text(
                "SELECT version_num FROM alembic_version"
            )) == "0017_agent_message_sequence"
    finally:
        engine.dispose()
