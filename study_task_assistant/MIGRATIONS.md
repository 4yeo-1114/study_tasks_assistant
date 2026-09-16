# 数据库表结构迁移

项目使用 Alembic 管理 `tasks` 表结构。`api.py` 启动时只创建 Engine 和 Session factory，不自动建表；先执行迁移，再启动服务。迁移文件位于 `migrations/versions/`，当前版本为 `0001_initial_tasks`。

在仓库根目录的 PowerShell 中，安装依赖后执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r study_task_assistant\requirements.txt
.\.venv\Scripts\python.exe -m alembic -c study_task_assistant\alembic.ini upgrade head
.\.venv\Scripts\python.exe -m alembic -c study_task_assistant\alembic.ini current
```

没有设置 `DATABASE_URL` 时，上述命令操作 `study_task_assistant/tasks.db`。若要迁移 PostgreSQL，先在当前终端设置 `DATABASE_URL` 为目标数据库连接串，再执行相同的 `upgrade head` 和 `current`。不要把真实密码写进文档或提交到 Git。

`upgrade head` 会按版本文件实际修改表结构，并在 `alembic_version` 记录已执行版本。`current` 只读取当前版本。`stamp 0001_initial_tasks` **只登记版本，不建表也不改表**；只有确认已有表结构与版本文件一致时才能用。仓库中原有的 PostgreSQL `study_tasks.tasks` 已核对后标记为此版本。

本地旧版 `tasks.db` 曾使用 TEXT 日期，如 `2026-9-10`，与当前 SQLAlchemy `Date` 不一致。它已由一次性脚本迁移；原文件备份为 `tasks-pre-alembic.db`，两条任务保留，日期规范为 `2026-09-10`。这两个 `.db` 文件被 Git 忽略。若在其他机器迁移同样的旧库，先停止使用它的程序，并在项目目录执行：

```powershell
..\.venv\Scripts\python.exe -c "from pathlib import Path; from legacy_sqlite_migration import migrate_legacy_sqlite; migrate_legacy_sqlite(Path('tasks.db'))"
```

该脚本会拒绝覆盖已有备份或临时数据库；不要对已经迁移过的数据库重复运行。
