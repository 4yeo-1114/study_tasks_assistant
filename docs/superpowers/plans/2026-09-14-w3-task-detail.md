# W3-AI-02 Task Detail Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 增加按正整数 ID 查询单条任务的 `GET /tasks/{task_id}` 接口及 404/422 行为。

**Architecture:** API 层声明并校验路径参数、映射 404；Service 层传递查询用例；Repository 使用参数化 SQL 返回字典或 `None`。复用现有 `TaskRead`，不增加新数据模型。

**Tech Stack:** Python 3.10、FastAPI 0.141.1、Pydantic 2.13.5、SQLite、pytest 9.1.1

## Global Constraints

- 不改变现有 GET 集合、status 筛选和 POST 行为。
- `task_id` 必须是大于等于 1 的整数，否则返回 422。
- 不存在的正整数 ID 返回 `404` 和 `{"detail": "找不到任务"}`。
- SQL 必须使用 `WHERE id = ?`。

---

### Task 1: 成功查询与不存在错误

**Files:**
- Modify: `study_task_assistant/test_api.py`
- Modify: `study_task_assistant/repository.py`
- Modify: `study_task_assistant/service.py`
- Modify: `study_task_assistant/api.py`

**Interfaces:**
- Produces: `repository.get_task(db_path, task_id: int) -> dict | None`
- Produces: `TaskService.get_task(task_id: int) -> dict | None`
- Produces: `GET /tasks/{task_id}` with `TaskRead`, 200 or 404

- [ ] **Step 1: Write failing HTTP behavior tests**

Create one task, assert `/tasks/1` returns the created JSON, then assert `/tasks/999` returns status 404 and `{"detail": "找不到任务"}`.

- [ ] **Step 2: Verify RED**

Run the two targeted tests. Expected: 404 for `/tasks/1` because the dynamic route is absent.

- [ ] **Step 3: Implement repository, service and route**

Repository executes:

```sql
SELECT id, title, status, priority, due_date
FROM tasks
WHERE id = ?
```

API first declares `task_id: int`, calls the service, raises `HTTPException(status_code=404, detail="找不到任务")` for `None`, and otherwise returns the task。正整数约束在 Task 2 通过独立 RED/GREEN 加入。

- [ ] **Step 4: Verify GREEN**

Run the targeted tests. Expected: both pass.

### Task 2: 路径参数校验与交接

**Files:**
- Modify: `study_task_assistant/test_api.py`
- Modify: `readme.md`
- Modify: `学习进度.md`
- Modify: `学习记录/2026-09-14-01.md`

**Interfaces:**
- Consumes: path constraint from Task 1
- Produces: non-integer and zero IDs return 422; current learning state is recorded

- [ ] **Step 1: Write and run path validation tests**

Assert `/tasks/not-an-int` and `/tasks/0` return 422. Run them before adding `Path(ge=1)`: the non-integer case already returns 422 from the `int` annotation, while zero returns 404, so the test set is RED for the missing positive-ID constraint.

- [ ] **Step 2: Add the positive-ID constraint and verify GREEN**

Change the route parameter to `task_id: Annotated[int, Path(ge=1)]`, then rerun the two validation cases and confirm both return 422.

- [ ] **Step 3: Run the full suite**

Run `..\.venv\Scripts\python.exe -m pytest -v` from `study_task_assistant`; all old and new tests must pass without modifying real `tasks.db`.

- [ ] **Step 4: Update documentation and evidence**

Document `GET /tasks/{task_id}`, explain path parameters, and record AI/user contribution without raising the learner's level solely because code passes.

- [ ] **Step 5: Commit exact W3-AI-02 files**

Run `git diff --check`, stage only the listed files plus this plan, rerun the full suite, and commit with a concise Conventional Commit message.
