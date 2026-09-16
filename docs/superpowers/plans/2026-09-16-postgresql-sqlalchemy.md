# PostgreSQL 与 SQLAlchemy 迁移 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让学习任务助手使用同一套 SQLAlchemy Repository 支持测试 SQLite 与实际 PostgreSQL，并验证连接池、事务和错误端口故障。

**Architecture:** `Database` 持有 SQLAlchemy Engine 与 session factory；`TaskRepository` 为每次操作创建短生命周期 Session；`TaskService` 只调用 Repository；FastAPI 应用负责组装与关闭 Engine。API 测试使用临时 SQLite，真实集成测试只使用专用 `study_tasks_test` PostgreSQL 数据库。

**Tech Stack:** Python 3.10、FastAPI 0.141.1、Pydantic 2.13.5、SQLAlchemy 2.0.54、psycopg 3.3.5、PostgreSQL 17、pytest 9.1.1

## Global Constraints

- 保持现有 `/tasks` 路由、JSON 字段和 HTTP 状态码不变。
- 使用同步 SQLAlchemy 2.0 ORM 和 psycopg 3，不引入异步数据库层。
- 生产连接只从 `DATABASE_URL` 读取；集成测试只从 `TEST_DATABASE_URL` 读取。
- 未设置 `DATABASE_URL` 时保留项目目录下 SQLite 默认库，保证模块可导入。
- 不提交真实数据库密码或 `.env`。
- PostgreSQL 集成测试必须拒绝数据库名不是 `study_tasks_test` 的 URL。
- schema migration、认证和用户隔离不在本计划实现。

---

### Task 1: 数据库对象、ORM 模型与 Repository CRUD

**Files:**
- Create: `study_task_assistant/database.py`
- Create: `study_task_assistant/models.py`
- Rewrite: `study_task_assistant/repository.py`
- Create: `study_task_assistant/test_repository.py`
- Modify: `study_task_assistant/requirements.txt`

**Interfaces:**
- Produces: `Database(url: str)`, `Database.sessions`, `Database.create_schema()`, `Database.dispose()`。
- Produces: `TaskRepository(session_factory)` 及 `list_tasks`、`get_task`、`create_task`、`update_task_status`、`delete_task`。
- Repository 返回包含 `id/title/status/priority/due_date` 的普通字典；`due_date` 为 ISO 日期字符串或 `None`。

- [ ] **Step 1: 添加并安装确定版本的依赖**

向 `requirements.txt` 添加：

```text
SQLAlchemy==2.0.54
psycopg[binary]==3.3.5
```

运行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r study_task_assistant\requirements.txt
```

预期：安装成功，`python -c "import sqlalchemy, psycopg"` 退出码为 0。

- [ ] **Step 2: 先写 Repository 行为测试**

创建 `test_repository.py`，测试使用文件型临时 SQLite：

```python
from datetime import date

from database import Database
from repository import TaskRepository


def test_repository_crud_uses_sessions_and_persists(tmp_path):
    url = f"sqlite+pysqlite:///{(tmp_path / 'repo.db').as_posix()}"
    database = Database(url)
    database.create_schema()
    repository = TaskRepository(database.sessions)

    created = repository.create_task(
        title="迁移 Repository",
        priority="high",
        due_date=date(2026, 9, 30),
    )
    assert created == {
        "id": 1,
        "title": "迁移 Repository",
        "status": "pending",
        "priority": "high",
        "due_date": "2026-09-30",
    }
    assert repository.get_task(1) == created
    assert repository.list_tasks(priority="high") == [created]
    assert repository.update_task_status(1, "completed")["status"] == "completed"
    assert repository.delete_task(1) is True
    assert repository.get_task(1) is None
    database.dispose()
```

- [ ] **Step 3: 运行测试并确认 RED**

运行：

```powershell
.\.venv\Scripts\python.exe -m pytest study_task_assistant\test_repository.py -q
```

预期：因 `database`/`models` 或 `TaskRepository` 尚不存在而失败；不能是测试语法错误。

- [ ] **Step 4: 实现 `models.py`**

定义 ORM 基类和任务表：

```python
from datetime import date

from sqlalchemy import CheckConstraint, Date, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'completed')", name="tasks_status_check"),
        CheckConstraint("priority IN ('high', 'medium', 'low')", name="tasks_priority_check"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    priority: Mapped[str] = mapped_column(String, nullable=False, default="medium")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
```

- [ ] **Step 5: 实现 `database.py`**

```python
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from models import Base


class Database:
    def __init__(self, url: str) -> None:
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(
            url,
            connect_args=connect_args,
            pool_pre_ping=True,
        )
        self.sessions = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
        )

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()
```

- [ ] **Step 6: 用最小 SQLAlchemy 实现重写 `repository.py`**

实现 `TaskRepository`。查询使用 `select(Task).order_by(Task.id)` 并按非空筛选条件追加 `.where()`；单条读取使用 `session.get(Task, task_id)`；写入使用 `with self._sessions.begin() as session:`。统一转换函数：

```python
def _task_to_dict(task: Task) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "due_date": task.due_date.isoformat() if task.due_date else None,
    }
```

创建时 `session.add(task)` 后调用 `session.flush()` 取得 ID；更新和删除找不到任务时返回 `None`/`False`；不要在 Repository 外暴露 ORM 对象。

- [ ] **Step 7: 运行 Repository 测试并确认 GREEN**

运行：

```powershell
.\.venv\Scripts\python.exe -m pytest study_task_assistant\test_repository.py -q
```

预期：`1 passed`。

- [ ] **Step 8: 提交 Task 1**

```powershell
git add study_task_assistant/database.py study_task_assistant/models.py study_task_assistant/repository.py study_task_assistant/test_repository.py study_task_assistant/requirements.txt
git commit -m "feat(db): add sqlalchemy task repository"
```

---

### Task 2: Service、FastAPI 组装与日期类型

**Files:**
- Modify: `study_task_assistant/schemas.py`
- Modify: `study_task_assistant/service.py`
- Modify: `study_task_assistant/api.py`
- Modify: `study_task_assistant/test_api.py`

**Interfaces:**
- Consumes: `Database` 和 `TaskRepository`。
- Produces: `normalize_database_url(value: str | Path) -> str`。
- Produces: `create_app(database: str | Path) -> FastAPI`，兼容现有 Path 测试并支持 SQLAlchemy URL。
- Produces: `get_default_database_url() -> str`，读取 `DATABASE_URL` 或返回项目 SQLite URL。

- [ ] **Step 1: 写 URL 接入的失败测试**

向 `test_api.py` 添加：

```python
def test_create_app_accepts_sqlalchemy_database_url(tmp_path):
    from api import create_app

    url = f"sqlite+pysqlite:///{(tmp_path / 'url.db').as_posix()}"
    with TestClient(create_app(url)) as client:
        response = client.post("/tasks", json={"title": "URL 配置"})

    assert response.status_code == 201
    assert response.json()["title"] == "URL 配置"
```

- [ ] **Step 2: 运行目标测试并确认 RED**

运行：

```powershell
.\.venv\Scripts\python.exe -m pytest study_task_assistant\test_api.py::test_create_app_accepts_sqlalchemy_database_url -q
```

预期：旧 `sqlite3.connect()` 把 URL 当文件路径而失败。

- [ ] **Step 3: 调整 Pydantic 日期类型**

将 `TaskCreate.due_date` 和 `TaskRead.due_date` 改为 `date | None`，删除手写 `datetime.strptime` 校验器。Pydantic 继续拒绝不存在的日期，并把 JSON 响应序列化为 `YYYY-MM-DD`。

- [ ] **Step 4: 改造 Service 依赖**

`TaskService.__init__` 接收 `TaskRepository`；删除路径字段和每次请求的 `initialize()`；所有方法直接调用 `self._repository`。方法名和返回值保持不变。

- [ ] **Step 5: 改造 FastAPI 应用工厂**

实现 URL 归一化：

```python
def normalize_database_url(value: str | Path) -> str:
    if isinstance(value, Path):
        return f"sqlite+pysqlite:///{value.resolve().as_posix()}"
    return value if "://" in value else f"sqlite+pysqlite:///{Path(value).resolve().as_posix()}"
```

`create_app()` 创建 `Database`、调用一次 `create_schema()`、构造 Repository/Service，并使用 lifespan 在关闭时 `database.dispose()`。把 database 保存到 `app.state.database` 方便验证。默认 URL：

```python
def get_default_database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        f"sqlite+pysqlite:///{Path(__file__).with_name('tasks.db').as_posix()}",
    )
```

- [ ] **Step 6: 运行 URL 目标测试并确认 GREEN**

运行同 Step 2，预期 `1 passed`。

- [ ] **Step 7: 运行全部 API 回归测试**

```powershell
.\.venv\Scripts\python.exe -m pytest study_task_assistant\test_api.py -q
```

预期：原 22 条加新增 1 条，共 `23 passed`；允许现有 Starlette/anyio 第三方弃用警告，不允许新增应用警告。

- [ ] **Step 8: 提交 Task 2**

```powershell
git add study_task_assistant/schemas.py study_task_assistant/service.py study_task_assistant/api.py study_task_assistant/test_api.py
git commit -m "refactor(api): use sqlalchemy database sessions"
```

---

### Task 3: 配置保护与 PostgreSQL 集成测试

**Files:**
- Create: `study_task_assistant/.env.example`
- Create: `study_task_assistant/test_postgres_integration.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `Database` 和 `TaskRepository`。
- Consumes: `TEST_DATABASE_URL`，且 URL 的 database 必须精确为 `study_tasks_test`。
- Produces: 一条 opt-in 真实 PostgreSQL CRUD 集成测试。

- [ ] **Step 1: 写 PostgreSQL 集成测试**

```python
import os

import pytest
from sqlalchemy.engine import make_url

from database import Database
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
    database.create_schema()
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
        database.dispose()
```

- [ ] **Step 2: 无环境变量运行并验证安全跳过**

```powershell
.\.venv\Scripts\python.exe -m pytest study_task_assistant\test_postgres_integration.py -q
```

预期：`1 skipped`，不会连接或清理任意数据库。

- [ ] **Step 3: 添加配置示例和忽略规则**

`.env.example`：

```dotenv
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@127.0.0.1:5432/study_tasks
TEST_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@127.0.0.1:5432/study_tasks_test
```

根 `.gitignore` 增加：

```gitignore
.env
study_task_assistant/.env
```

- [ ] **Step 4: 创建专用测试数据库**

先查询，再只在不存在时创建：

```powershell
docker exec study-postgres psql -U study -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='study_tasks_test'"
docker exec study-postgres psql -U study -d postgres -c "CREATE DATABASE study_tasks_test OWNER study"
```

第二条命令仅在第一条没有输出 `1` 时执行。

- [ ] **Step 5: 使用容器已有凭据运行真实集成测试**

在 PowerShell 中从容器配置读取密码到进程变量，不把值写入输出或文件；对密码做 URL 编码后构造 `TEST_DATABASE_URL`，运行目标测试。预期：`1 passed`，结束后测试数据库不存在 `tasks` 表。

- [ ] **Step 6: 运行全部本地测试**

```powershell
.\.venv\Scripts\python.exe -m pytest study_task_assistant -q
```

预期：Repository 和 API 共 24 条通过，PostgreSQL 测试在未设置 URL 的普通运行中跳过。

- [ ] **Step 7: 检查敏感信息和提交**

```powershell
git diff --check
git status --short
git add .gitignore study_task_assistant/.env.example study_task_assistant/test_postgres_integration.py
git commit -m "test(db): add isolated postgres integration test"
```

提交前确认 diff 中没有实际密码。

---

### Task 4: 实际服务、psql 对账与故障实验

**Files:**
- Modify: `学习记录/2026-09-16-01.md`
- Modify: `学习进度.md`

**Interfaces:**
- Consumes: `DATABASE_URL` 指向 `study_tasks`。
- Produces: HTTP POST/GET 与 PostgreSQL `tasks` 表一致的证据。
- Produces: 错误端口连接异常的学习证据，但不将 AI 的定位记为用户独立 L3。

- [ ] **Step 1: 用 PostgreSQL URL 启动实际服务**

在不打印密码的 PowerShell 进程中设置 `DATABASE_URL`，运行：

```powershell
.\.venv\Scripts\python.exe -m uvicorn api:app --app-dir study_task_assistant --host 127.0.0.1 --port 8000
```

预期：Uvicorn 启动，PostgreSQL 出现 `tasks` 表。

- [ ] **Step 2: 通过 HTTP 创建并读取任务**

```powershell
curl.exe -s -X POST http://127.0.0.1:8000/tasks -H "Content-Type: application/json" -d '{"title":"PostgreSQL API","priority":"high","due_date":"2026-09-30"}'
curl.exe -s http://127.0.0.1:8000/tasks
```

预期：POST 为 201，GET 包含同一任务。

- [ ] **Step 3: 用 psql 对账**

```powershell
docker exec study-postgres psql -U study -d study_tasks -c "SELECT id,title,status,priority,due_date FROM tasks ORDER BY id;"
```

预期：能查到 HTTP 创建的 `PostgreSQL API`，字段一致。

- [ ] **Step 4: 运行错误端口故障实验**

停止测试服务后，把 URL 端口临时改成 `55432` 并启动。记录异常类型和包含 `127.0.0.1:55432`、connection refused/连接失败的关键行；随后恢复正确 URL。不要提交错误 URL 或密码。

- [ ] **Step 5: 最终验证**

运行完整测试、`git diff --check`、`git status --short`；复核容器 `pg_isready` 和正确 URL 的 API GET。

- [ ] **Step 6: 更新教学记录并提交**

记录 AI 实现、用户待完成的解释题、实际测试数量和故障实验归属。更新 `学习进度.md` 的当前任务为 W4-AI-05 待用户验收。

```powershell
git add 学习进度.md 学习记录/2026-09-16-01.md
git commit -m "docs(w4): record sqlalchemy postgres migration"
```
