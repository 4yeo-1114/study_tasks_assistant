"""One-time conversion of the pre-SQLAlchemy local SQLite database."""

import os
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from migration import upgrade_database


def migrate_legacy_sqlite(path: Path) -> None:
    path = path.resolve()
    backup = path.with_name(f"{path.stem}-pre-alembic.db")
    migrated = path.with_name(f"{path.stem}-migrated.db")
    if not path.is_file():
        raise FileNotFoundError(path)
    if backup.exists() or migrated.exists():
        raise FileExistsError("备份或临时数据库已存在；停止以免覆盖数据")

    with closing(sqlite3.connect(path)) as connection:
        rows = connection.execute(
            "SELECT id,title,status,priority,due_date FROM tasks ORDER BY id"
        ).fetchall()

    converted = [
        (
            task_id,
            title,
            status,
            priority,
            datetime.strptime(due_date, "%Y-%m-%d").date().isoformat()
            if due_date is not None
            else None,
        )
        for task_id, title, status, priority, due_date in rows
    ]

    shutil.copy2(path, backup)
    try:
        upgrade_database(f"sqlite+pysqlite:///{migrated.as_posix()}")
        with closing(sqlite3.connect(migrated)) as connection:
            with connection:
                connection.executemany(
                    "INSERT INTO tasks (id,title,status,priority,due_date) "
                    "VALUES (?,?,?,?,?)",
                    converted,
                )
                copied = connection.execute(
                    "SELECT id,title,status,priority,due_date FROM tasks ORDER BY id"
                ).fetchall()
        if copied != converted:
            raise RuntimeError("迁移后数据核对不一致，原数据库保持不变")
        os.replace(migrated, path)
    finally:
        if migrated.exists():
            migrated.unlink()
