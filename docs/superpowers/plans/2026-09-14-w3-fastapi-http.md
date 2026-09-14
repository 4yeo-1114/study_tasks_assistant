# W3 FastAPI 与 HTTP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为现有学习任务助手增加可运行、可测试且使用 SQLite 的 `GET /tasks` 与 `POST /tasks` FastAPI 接口。

**Architecture:** `api.py` 只处理 HTTP，`schemas.py` 声明 Pydantic 输入输出，`service.py` 表达用例，`repository.py` 执行参数化 SQLite。应用工厂接收数据库路径，正式环境使用现有 `tasks.db`，测试使用 pytest 临时目录。

**Tech Stack:** Python 3.10、FastAPI、Pydantic 2、Uvicorn、SQLite、pytest、HTTPX/TestClient

## Global Constraints

- 保留现有 `main.py` CLI 行为和兼容字段，不做无关重构。
- 首版只实现 `GET /tasks` 与 `POST /tasks`。
- 测试不得读写真实 `study_task_assistant/tasks.db`。
- 所有 SQL 使用 `?` 参数，不拼接请求数据。
- 用 TDD 逐项观察 RED 与 GREEN；最终运行新旧全部测试。
- 本轮由 AI 完成骨架和基础测试；`status` 查询参数变式留给学习者。

---

## File Map

- Create `study_task_assistant/requirements.txt`: W3 运行和测试依赖。
- Create `study_task_assistant/schemas.py`: `TaskCreate` 与 `TaskRead` Pydantic 模型。
- Create `study_task_assistant/repository.py`: SQLite 建表、查询和新增。
- Create `study_task_assistant/service.py`: 查询和新增用例边界。
- Create `study_task_assistant/api.py`: 应用工厂、默认应用和两个路由。
- Create `study_task_assistant/test_api.py`: HTTP 行为测试。
- Modify `readme.md`: 安装、启动、请求和测试命令。
- Modify `学习进度.md`: W3 状态及下一次验收入口。
- Create `学习记录/2026-09-14-01.md`: AI 实现、验证结果和用户待完成项。

### Task 1: 依赖与空列表查询

**Files:**
- Create: `study_task_assistant/requirements.txt`
- Create: `study_task_assistant/test_api.py`
- Create: `study_task_assistant/repository.py`
- Create: `study_task_assistant/service.py`
- Create: `study_task_assistant/schemas.py`
- Create: `study_task_assistant/api.py`

**Interfaces:**
- Produces: `create_app(db_path: str | Path) -> FastAPI`
- Produces: `init_db(db_path) -> None`, `list_tasks(db_path) -> list[dict]`
- Produces: `TaskService.list_tasks() -> list[dict]`

- [ ] **Step 1: Add and install exact W3 dependencies**

Write these Python 3.10 compatible packages to `requirements.txt`:

```text
fastapi==0.141.1
uvicorn==0.52.4
httpx==0.28.1
```

Then run:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\study_task_assistant\requirements.txt
```

- [ ] **Step 2: Write the failing empty-list test**

```python
def test_get_tasks_returns_empty_list(tmp_path):
    from api import create_app

    client = TestClient(create_app(tmp_path / "test.db"))
    response = client.get("/tasks")
    assert response.status_code == 200
    assert response.json() == []
```

- [ ] **Step 3: Run the test and verify RED**

Run from `study_task_assistant`:

```powershell
..\.venv\Scripts\python.exe -m pytest test_api.py::test_get_tasks_returns_empty_list -v
```

Expected: FAIL because `api` or `create_app` does not exist yet.

- [ ] **Step 4: Implement the minimum GET path**

Create compatible `tasks` table initialization in `repository.py`, a `SELECT id, title, status, priority, due_date ORDER BY id`, a pass-through `TaskService.list_tasks`, `TaskRead`, and this application boundary:

```python
def create_app(db_path: str | Path) -> FastAPI:
    app = FastAPI(title="Study Task Assistant")
    service = TaskService(db_path)
    service.initialize()

    @app.get("/tasks", response_model=list[TaskRead])
    def get_tasks():
        return service.list_tasks()

    return app
```

Create `app = create_app(Path(__file__).with_name("tasks.db"))` for Uvicorn.

- [ ] **Step 5: Verify GREEN**

Run the same targeted test. Expected: `1 passed`.

### Task 2: 新增任务与持久化

**Files:**
- Modify: `study_task_assistant/test_api.py`
- Modify: `study_task_assistant/schemas.py`
- Modify: `study_task_assistant/repository.py`
- Modify: `study_task_assistant/service.py`
- Modify: `study_task_assistant/api.py`

**Interfaces:**
- Consumes: `create_app`, `TaskService`, repository table from Task 1
- Produces: `TaskCreate(title, priority='medium', due_date=None)`
- Produces: `create_task(db_path, task: TaskCreate) -> dict`
- Produces: `POST /tasks -> 201 + TaskRead`

- [ ] **Step 1: Write a failing POST persistence test**

The test posts `{"title": "学习 FastAPI", "priority": "high"}`, asserts `201`, ID `1`, status `pending`, then calls `GET /tasks` and asserts the new task is present.

- [ ] **Step 2: Verify RED**

Run the targeted POST test. Expected: FAIL with `405 Method Not Allowed` because the route does not exist.

- [ ] **Step 3: Implement the minimum POST path**

Add `TaskCreate`, execute a parameterized `INSERT`, commit, read the inserted row, and add:

```python
@app.post("/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def post_task(task: TaskCreate):
    return service.create_task(task)
```

- [ ] **Step 4: Verify GREEN and regression**

Run both API tests. Expected: `2 passed` and the GET behavior remains unchanged.

### Task 3: 请求校验与 HTTP 错误

**Files:**
- Modify: `study_task_assistant/test_api.py`
- Modify: `study_task_assistant/schemas.py`

**Interfaces:**
- Consumes: `TaskCreate` and both routes
- Produces: whitespace title, unknown priority and invalid date return `422`; unknown path returns `404`

- [ ] **Step 1: Write failing validation tests**

Add parameterized requests for blank title, priority `urgent`, and date `2026-02-30`. Each must return `422`; a final GET must still return `[]`. Add a separate `GET /missing` assertion for `404`.

- [ ] **Step 2: Verify RED**

Run only validation tests. Expected: at least one invalid request returns `201`, proving constraints are missing.

- [ ] **Step 3: Add exact Pydantic constraints**

Use `StringConstraints(strip_whitespace=True, min_length=1)`, `Literal['high', 'medium', 'low']`, and a `field_validator` that parses non-null dates with `datetime.strptime(value, '%Y-%m-%d')` and raises `ValueError` for nonexistent dates.

- [ ] **Step 4: Verify GREEN and full API suite**

Run `pytest test_api.py -v`. Expected: all API tests pass and invalid requests create no rows.

### Task 4: 兼容性、运行说明与学习交接

**Files:**
- Modify: `readme.md`
- Modify: `学习进度.md`
- Create: `学习记录/2026-09-14-01.md`

**Interfaces:**
- Consumes: final `app`, requirements and tests
- Produces: reproducible W3 commands and a pending learner exercise

- [ ] **Step 1: Run all automated tests**

From `study_task_assistant` run:

```powershell
..\.venv\Scripts\python.exe -m pytest -v
```

Expected: existing CLI tests and new API tests all pass.

- [ ] **Step 2: Smoke-test the real server without changing real task data**

From `study_task_assistant`, start `..\.venv\Scripts\python.exe -m uvicorn api:app --host 127.0.0.1 --port 8765` in a hidden child process. Send GET requests to `http://127.0.0.1:8765/tasks` and `http://127.0.0.1:8765/docs`, record both status codes, and stop that exact child process in `finally`. GET requests do not modify the real task database. Confirm both responses return `200`.

- [ ] **Step 3: Document reproducible commands**

Add dependency installation, `uvicorn api:app --reload`, `/docs`, example GET/POST requests, status-code meanings, and pytest commands to `readme.md`.

- [ ] **Step 4: Update factual learning records**

Record that AI implemented the skeleton and tests. Set W3-AI-01 to “进行中/待用户验收”; do not raise HTTP beyond L0 until the user runs and explains it. Set the next action to user execution, one fault experiment, and the independent `status` filter variation.

- [ ] **Step 5: Check the diff and commit only W3 files**

Run `git diff --check`, stage the files listed in this plan, run the full tests again against the staged state, and commit with a concise Conventional Commit message.
