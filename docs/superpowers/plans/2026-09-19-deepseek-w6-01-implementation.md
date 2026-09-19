# DeepSeek W6-01 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fake-model-first W6 entry with a real, safe DeepSeek Chat Completions exercise while keeping all automated tests offline.

**Architecture:** A focused `deepseek_api.py` module owns environment configuration, one non-streaming HTTP request, response parsing, and safe API errors. A separate demo is the only command-line entry point; it reads the API key from the environment and prints the response and usage without printing credentials. The existing Fake Client remains an offline teaching/test double, while curriculum documents make real DeepSeek calls the W6 main line and tool calls the W7 main line.

**Tech Stack:** Python 3.10.11, `httpx==0.28.1`, pytest 9.1.1, DeepSeek OpenAI-compatible `POST /chat/completions` API, PowerShell.

## Global Constraints

- Never place `DEEPSEEK_API_KEY` in source code, `.env.example`, tests, logs, Git diffs, or learning records.
- Default `DEEPSEEK_BASE_URL` is `https://api.deepseek.com`; trim one trailing slash before appending `/chat/completions`.
- Read `DEEPSEEK_MODEL` from the environment and use `deepseek-flash` only as the example/default value documented from the 2026-09-19 official page.
- Automated tests must use `httpx.MockTransport`; they must not access the network or consume API balance.
- Preserve the current Fake Client for deterministic offline exercises.
- Preserve unrelated working-tree changes in `api.py`, `auth.py`, `w3-w4总结.md`, old learning logs, and `sqlite_practice.py`.
- This plan implements W6-01 only; streaming, multi-round state, retries, tool calls, and database execution remain later units.

---

## File Structure

- Create `study_task_assistant/deepseek_api.py`: settings, reply/usage value objects, safe exceptions, and one non-streaming request.
- Create `study_task_assistant/deepseek_demo.py`: command-line input, environment loading, one real request, and readable output.
- Create `study_task_assistant/test_deepseek_api.py`: offline request-contract, configuration, parsing, and safe-error tests.
- Modify `study_task_assistant/requirements.txt`: replace unused `httpx2` with the imported `httpx` package at the installed compatible version.
- Modify `study_task_assistant/.env.example`: add non-secret DeepSeek variable names and placeholders.
- Modify `w5总结-w6-w7计划.md`: replace the old fake-first W6 and RAG-in-W7 schedule with the approved DeepSeek API and Agent schedule.
- Modify `学习进度.md`: record the curriculum change, preserve Fake Client evidence as AI scaffold, and make the real API exercise the next action.
- Create `学习记录/2026-09-19-02.md`: record the plan change, AI contribution, verification, and remaining user evidence.

### Task 1: Offline-tested DeepSeek request contract

**Files:**
- Create: `study_task_assistant/test_deepseek_api.py`
- Create: `study_task_assistant/deepseek_api.py`
- Modify: `study_task_assistant/requirements.txt`
- Modify: `study_task_assistant/.env.example`

**Interfaces:**
- Consumes: existing `model_client.ModelMessage(role, content)`.
- Produces: `DeepSeekSettings.from_env() -> DeepSeekSettings`, `DeepSeekUsage`, `DeepSeekReply`, `DeepSeekConfigurationError`, `DeepSeekAPIError`, `DeepSeekResponseError`, and `request_chat(messages, *, settings, timeout_seconds=30.0, transport=None) -> DeepSeekReply`.

- [x] **Step 1: Write failing configuration and request tests**

Create tests that clear DeepSeek variables and expect `DeepSeekSettings.from_env()` to reject a missing key without exposing any credential. Add an `httpx.MockTransport` handler that asserts:

```python
assert request.method == "POST"
assert request.url == "https://api.deepseek.com/chat/completions"
assert request.headers["Authorization"] == "Bearer test-key"
payload = json.loads(request.content)
assert payload == {
    "model": "test-model",
    "messages": [{"role": "user", "content": "用一句话解释 API"}],
    "stream": False,
}
```

Return a fixed 200 response containing `choices[0].message.content`, `model`, and all three usage counts. Assert the parsed `DeepSeekReply`. Add a 401 response containing a provider error and assert `DeepSeekAPIError.status_code == 401` while `"test-key" not in str(error)`. Add a 200 response without `choices` and assert `DeepSeekResponseError` so malformed success responses cannot be mistaken for valid answers.

- [x] **Step 2: Run the focused tests and verify the red state**

Run:

```powershell
cd D:\dev-learning\study_task_assistant
python -m pytest test_deepseek_api.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'deepseek_api'`.

- [x] **Step 3: Implement the minimal request module**

Implement immutable dataclasses with these exact fields:

```python
@dataclass(frozen=True)
class DeepSeekSettings:
    api_key: str
    base_url: str
    model: str

@dataclass(frozen=True)
class DeepSeekUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

@dataclass(frozen=True)
class DeepSeekReply:
    text: str
    model: str
    usage: DeepSeekUsage
```

`DeepSeekSettings.from_env()` reads `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, and `DEEPSEEK_MODEL`; it raises `DeepSeekConfigurationError("缺少环境变量 DEEPSEEK_API_KEY")` when the key is missing or blank. `request_chat` rejects non-positive timeouts, posts the exact payload asserted above, converts non-2xx responses to `DeepSeekAPIError(status_code, provider_message)`, and converts missing or wrongly typed success fields to `DeepSeekResponseError`. It returns `DeepSeekReply` only after validation. Accept optional `httpx.BaseTransport` only to support offline tests.

- [x] **Step 4: Correct dependencies and environment template**

Replace:

```text
httpx2==2.12.0
```

with:

```text
httpx==0.28.1
```

Append these non-secret example values to `.env.example`:

```dotenv
DEEPSEEK_API_KEY=REPLACE_WITH_YOUR_DEEPSEEK_API_KEY
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
```

- [x] **Step 5: Run focused and full tests**

Run:

```powershell
python -m pytest test_deepseek_api.py -q
python -m pytest -q
```

Expected: the focused tests pass; the existing suite remains green with only the already documented PostgreSQL skip when `TEST_DATABASE_URL` is absent and the existing Starlette deprecation warning.

- [x] **Step 6: Commit the request contract**

```powershell
git add -- study_task_assistant/deepseek_api.py study_task_assistant/test_deepseek_api.py study_task_assistant/requirements.txt study_task_assistant/.env.example
git diff --cached --check
git commit -m "feat(agent): add DeepSeek chat API client"
```

### Task 2: Safe real-call demonstration

**Files:**
- Create: `study_task_assistant/deepseek_demo.py`
- Test: `study_task_assistant/test_deepseek_api.py`

**Interfaces:**
- Consumes: `DeepSeekSettings.from_env()` and `request_chat(...)` from Task 1.
- Produces: `main(argv: Sequence[str] | None = None) -> int`, with exit code 0 on success and 1 for a configuration/API/network/response error.

- [x] **Step 1: Add failing tests for prompt selection and safe output**

Extract `prompt_from_args(argv)` so tests can assert that no argument uses `"请用一句话解释 HTTP API 是什么"` and multiple arguments join with spaces. Test `main()` by monkeypatching `request_chat` to return a fixed `DeepSeekReply`; assert output contains the model, reply, and `prompt/completion/total` token counts, and does not contain the test API key.

- [x] **Step 2: Run the demo-focused tests and verify failure**

Run:

```powershell
python -m pytest test_deepseek_api.py -q
```

Expected: import or assertion failure because `deepseek_demo.py` does not exist.

- [x] **Step 3: Implement the demonstration CLI**

Implement this data flow:

```python
settings = DeepSeekSettings.from_env()
messages = [ModelMessage(role="user", content=prompt_from_args(argv))]
reply = request_chat(messages, settings=settings, timeout_seconds=30)
```

Print only the selected model, final text, and usage counts. Catch the module's configuration/API/response exceptions plus `httpx.TimeoutException` and `httpx.RequestError`; print a short error to stderr and return 1. Never print `settings`, request headers, or the API key.

- [x] **Step 4: Run offline verification**

```powershell
python -m pytest test_deepseek_api.py -q
python -m py_compile deepseek_api.py deepseek_demo.py
```

Expected: all focused tests pass and compilation exits 0. Do not perform the real API call because the user's key and paid balance are external state.

- [x] **Step 5: Commit the demo**

```powershell
git add -- study_task_assistant/deepseek_demo.py study_task_assistant/test_deepseek_api.py
git diff --cached --check
git commit -m "feat(agent): add DeepSeek API learning demo"
```

### Task 3: Replace W6/W7 curriculum and hand off W6-01

**Files:**
- Modify: `w5总结-w6-w7计划.md`
- Modify: `学习进度.md`
- Create: `学习记录/2026-09-19-02.md`

**Interfaces:**
- Consumes: the approved design at `docs/superpowers/specs/2026-09-19-deepseek-api-w6-w7-design.md` and the runnable files from Tasks 1–2.
- Produces: one consistent dynamic next action and evidence record; no runtime interface.

- [x] **Step 1: Rewrite the W6 and W7 schedule**

Replace the old `W6：最小工具型 Agent` section with W6-01 through W6-05 from the approved design: real request, `httpx`/errors, multi-round usage, SSE streaming, and client engineering. Replace the old RAG-centered W7 section with W7-01 through W7-05: tool call, read-only task tools, Agent loop, confirmed writes, and reliability/evaluation. State that RAG moves to W8 and that the Fake Client remains only for offline tests.

- [x] **Step 2: Update the progress source of truth**

Change the current stage to real DeepSeek API learning. Keep the Fake Client implementation evidence but mark its user execution/understanding unverified. Add a new W6-API-01 row in progress with AI scaffold status and no user mastery claim. Set the next action to:

```powershell
cd D:\dev-learning\study_task_assistant
$env:DEEPSEEK_API_KEY="在本机填写，不要发给 AI"
$env:DEEPSEEK_BASE_URL="https://api.deepseek.com"
$env:DEEPSEEK_MODEL="deepseek-flash"
$body = @{model=$env:DEEPSEEK_MODEL; messages=@(@{role="user"; content="用一句话解释 HTTP API"}); stream=$false} | ConvertTo-Json -Depth 4 -Compress
curl.exe -sS "$env:DEEPSEEK_BASE_URL/chat/completions" -H "Content-Type: application/json" -H "Authorization: Bearer $env:DEEPSEEK_API_KEY" -d $body
python deepseek_demo.py
python -m pytest test_deepseek_api.py -q
```

Ask the learner to share only redacted output and answer where the URL, Authorization header, request messages, response text, and usage counts occur.

- [x] **Step 3: Record the implementation session**

Create `学习记录/2026-09-19-02.md` with AI contribution level H4, exact offline test commands and results, no claimed real API success, and the remaining user evidence: local key setup, one real call, output explanation, and one later parameter variation.

- [x] **Step 4: Verify consistency and secret hygiene**

Run:

```powershell
rg -n "不依赖付费 API|假模型响应让|W7：可靠性、评测与最小检索" w5总结-w6-w7计划.md 学习进度.md
rg -n "sk-[A-Za-z0-9]{16,}" study_task_assistant docs 学习进度.md 学习记录
rg -n "DEEPSEEK_API_KEY=" study_task_assistant/.env.example docs 学习进度.md 学习记录
git diff --check -- w5总结-w6-w7计划.md 学习进度.md 学习记录/2026-09-19-02.md
```

Expected: the first search finds no stale curriculum text; the key-shaped search finds no result; the environment-variable search shows only placeholders or command syntax, never a real value; diff check exits 0.

- [x] **Step 5: Run final project verification**

```powershell
cd D:\dev-learning\study_task_assistant
python -m pytest -q
python -m py_compile deepseek_api.py deepseek_demo.py
cd ..
git diff --check
```

Expected: all tests pass except the documented environment-dependent skip; compilation and diff check exit 0.

- [x] **Step 6: Commit only curriculum and learning records**

```powershell
git add -- w5总结-w6-w7计划.md 学习进度.md 学习记录/2026-09-19-02.md
git diff --cached --check
git commit -m "docs(learning): start real DeepSeek API track"
```

After the commit, verify `git status --short` still shows the learner's pre-existing files untouched.
