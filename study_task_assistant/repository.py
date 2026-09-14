import sqlite3
from contextlib import closing
from pathlib import Path


DatabasePath = str | Path


def init_db(db_path: DatabasePath) -> None:
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                priority TEXT NOT NULL DEFAULT 'medium',
                due_date TEXT
            )
            """
        )
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
        }
        if "priority" not in columns:
            connection.execute(
                "ALTER TABLE tasks ADD COLUMN priority TEXT DEFAULT 'medium'"
            )
        if "due_date" not in columns:
            connection.execute("ALTER TABLE tasks ADD COLUMN due_date TEXT")
        connection.commit()


def list_tasks(db_path: DatabasePath, status: str | None = None) -> list[dict]:
    with closing(sqlite3.connect(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        if status is None:
            rows = connection.execute(
                """
                SELECT id, title, status, priority, due_date
                FROM tasks
                ORDER BY id
                """
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT id, title, status, priority, due_date
                FROM tasks
                WHERE status = ?
                ORDER BY id
                """,
                (status,),
            ).fetchall()
    return [dict(row) for row in rows]


def create_task(
    db_path: DatabasePath,
    *,
    title: str,
    priority: str,
    due_date: str | None,
) -> dict:
    with closing(sqlite3.connect(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        cursor = connection.execute(
            """
            INSERT INTO tasks (title, status, priority, due_date)
            VALUES (?, 'pending', ?, ?)
            """,
            (title, priority, due_date),
        )
        connection.commit()
        row = connection.execute(
            """
            SELECT id, title, status, priority, due_date
            FROM tasks
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
    if row is None:
        raise RuntimeError("新增任务后无法读取数据")
    return dict(row)
