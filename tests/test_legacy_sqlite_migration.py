import sqlite3
from contextlib import closing

from storage.legacy_sqlite_migration import migrate_legacy_sqlite


def test_legacy_sqlite_rows_are_preserved_and_dates_normalized(tmp_path):
    path = tmp_path / "tasks.db"
    with closing(sqlite3.connect(path)) as connection:
        with connection:
            connection.execute(
                "CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT NOT NULL, "
                "status TEXT DEFAULT 'pending', priority TEXT DEFAULT 'medium', "
                "due_date TEXT)"
            )
            connection.execute(
                "INSERT INTO tasks VALUES (7, '旧任务', 'pending', 'low', '2026-9-10')"
            )

    migrate_legacy_sqlite(path)

    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute(
            "SELECT id,title,status,priority,due_date FROM tasks"
        ).fetchone() == (7, "旧任务", "pending", "low", "2026-09-10")
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
                ).fetchone() == ("0008_task_proposal_idempotency",)

    backup = tmp_path / "tasks-pre-alembic.db"
    with closing(sqlite3.connect(backup)) as connection:
        assert connection.execute("SELECT due_date FROM tasks").fetchone() == (
            "2026-9-10",
        )
