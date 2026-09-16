from sqlalchemy import create_engine, inspect, text

from migration import upgrade_database


def test_create_app_does_not_create_schema(tmp_path):
    from api import create_app

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
        assert "alembic_version" in inspector.get_table_names()
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == "0001_initial_tasks"
    finally:
        engine.dispose()
