# Task Status Update and Delete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a status-only PATCH endpoint and a DELETE endpoint for tasks, with validation, persistence, HTTP error behavior, and regression tests.

**Architecture:** Keep the existing API → TaskService → Repository → SQLite flow. Pydantic validates the PATCH body, the API converts missing resources to 404, Service coordinates calls, and Repository performs parameterized writes and commits them.

**Tech Stack:** Python 3.10, FastAPI, Pydantic, sqlite3, pytest, FastAPI TestClient

## Global Constraints

- PATCH only updates `status`; accepted values are `pending` and `completed`.
- Successful PATCH returns 200 and a `TaskRead` response.
- Successful DELETE returns 204 with an empty response body.
- Missing tasks return `{"detail": "找不到任务"}` with 404.
- Invalid IDs and invalid PATCH bodies return 422 before database access.
- SQL values use `?` parameters; successful writes are committed.
- The repeated-completion test is reserved for the learner's independent variation.

---

### Task 1: Define and test the PATCH contract

**Files:**
- Modify: `study_task_assistant/test_api.py`
- Modify: `study_task_assistant/schemas.py`
- Modify: `study_task_assistant/api.py`
- Modify: `study_task_assistant/service.py`
- Modify: `study_task_assistant/repository.py`

**Interfaces:**
- Produces: `TaskStatus`, `TaskStatusUpdate`, `TaskService.update_task_status()`, `repository.update_task_status()`, `PATCH /tasks/{task_id}`

- [x] **Step 1: Write failing API tests**

Add tests that create a task and PATCH it to completed, verify a following GET is completed, reject `{"status": "invalid"}` without changing the task, and return the Chinese 404 detail for ID 999.

- [x] **Step 2: Run tests and verify RED**

Run:

```powershell
..\.venv\Scripts\python.exe -m pytest -q test_api.py -k "patch"
```

Expected: the new tests fail because PATCH currently returns 405.

- [x] **Step 3: Add the request schema**

In `schemas.py`, add:

```python
TaskStatus = Literal["pending", "completed"]


class TaskStatusUpdate(BaseModel):
    status: TaskStatus
```

- [x] **Step 4: Add Repository and Service operations**

Add `repository.update_task_status(db_path, task_id, task_status) -> dict | None`. Execute `UPDATE tasks SET status = ? WHERE id = ?`, return `None` when `rowcount` is zero, commit successful changes, then select and return the updated task.

Add `TaskService.update_task_status(task_id, task_status) -> dict | None`, initialize the database and delegate to Repository.

- [x] **Step 5: Add the PATCH route**

Add `PATCH /tasks/{task_id}` with the existing positive-ID constraint, `TaskStatusUpdate` request body and `TaskRead` response model. Convert a `None` service result to the existing Chinese 404 response.

- [x] **Step 6: Run PATCH tests and full tests**

Run the targeted command from Step 2, then:

```powershell
..\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass.

### Task 2: Define and test the DELETE contract

**Files:**
- Modify: `study_task_assistant/test_api.py`
- Modify: `study_task_assistant/api.py`
- Modify: `study_task_assistant/service.py`
- Modify: `study_task_assistant/repository.py`

**Interfaces:**
- Produces: `TaskService.delete_task()`, `repository.delete_task()`, `DELETE /tasks/{task_id}`

- [x] **Step 1: Write failing API tests**

Add tests that delete an existing task and assert 204 plus an empty body, verify the following GET returns 404, and verify deleting ID 999 returns the Chinese 404 detail.

- [x] **Step 2: Run tests and verify RED**

Run:

```powershell
..\.venv\Scripts\python.exe -m pytest -q test_api.py -k "delete"
```

Expected: the new tests fail because DELETE currently returns 405.

- [x] **Step 3: Add Repository and Service operations**

Add `repository.delete_task(db_path, task_id) -> bool`. Execute `DELETE FROM tasks WHERE id = ?`, commit, and return whether `rowcount` is greater than zero.

Add `TaskService.delete_task(task_id) -> bool`, initialize the database and delegate to Repository.

- [x] **Step 4: Add the DELETE route**

Add `DELETE /tasks/{task_id}` with the existing positive-ID constraint. Convert `False` to the existing 404 response; return an explicit FastAPI `Response` with status 204 for success.

- [x] **Step 5: Run DELETE tests and full tests**

Run the targeted command from Step 2, then the full pytest suite. Expected: all tests pass and the successful DELETE body has zero bytes.

### Task 3: Verify invalid path handling and hand off the learner variation

**Files:**
- Modify: `study_task_assistant/test_api.py`
- Modify: `学习记录/2026-09-15-01.md`
- Modify: `学习进度.md`

**Interfaces:**
- Verifies: PATCH and DELETE reject zero and non-integer task IDs with 422.

- [x] **Step 1: Add failing or immediately applicable path tests**

Exercise PATCH and DELETE with `/tasks/0` and `/tasks/not-an-int`. Assert 422 for each request. These tests verify the route declarations reuse the positive-ID contract.

- [x] **Step 2: Run focused and full verification**

Run:

```powershell
..\.venv\Scripts\python.exe -m pytest -q test_api.py
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m py_compile api.py schemas.py service.py repository.py test_api.py
```

Expected: every command exits with code 0.

- [x] **Step 3: Update learning records**

Record the RED/GREEN evidence and AI contribution. Leave W3-AI-05 awaiting learner acceptance until the learner independently adds the repeated-completion test and explains the status codes and PATCH data flow.

- [x] **Step 4: Commit the implementation**

Stage only the five project source/test files and the two current learning records. Commit with:

```text
feat(api): update and delete tasks
```
