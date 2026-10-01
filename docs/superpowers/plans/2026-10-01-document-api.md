# Authenticated Document API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add owner-scoped document upload, rebuild, read, and delete endpoints backed by the existing lifecycle and pgvector ingestion pipeline.

**Architecture:** A new `DocumentService` wraps lifecycle, ingestion, embedding, and vector storage. `KnowledgeRuntime` shares the expensive model/store with both Agent retrieval and document management; FastAPI only handles authentication, validation, serialization, and HTTP error mapping.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2, PostgreSQL, pgvector, FastEmbed, pytest.

## Global Constraints

- `owner_id` comes only from JWT and must be included in document SQL predicates.
- Failed rebuilds preserve the previous ready/active version.
- Tests live under `tests/`; the user is not asked to write pytest code.
- The embedding model is shared process-wide and loaded lazily.

---

### Task 1: Owner-scoped document service

**Files:**
- Create: `study_task_assistant/document_service.py`
- Modify: `study_task_assistant/document_lifecycle.py`
- Test: `tests/test_document_service.py`

**Interfaces:**
- Produces: `DocumentService.ingest(owner_id, request)`, `list(owner_id)`, `get(owner_id, document_id)`, and `delete(owner_id, document_id)`.
- Consumes: `ingest_document`, `DocumentLifecycle`, `PgVectorStore`, and `EmbeddingModel`.

- [ ] Write failing service tests for upload, list/get isolation, conflict, and owner-scoped delete.
- [ ] Run `python -m pytest tests/test_document_service.py -q` and confirm failures are caused by the missing service and owner-scoped lifecycle operations.
- [ ] Implement the minimal service and lifecycle queries with owner predicates.
- [ ] Run the service tests and existing lifecycle/ingestion tests.

### Task 2: Share ingestion dependencies through KnowledgeRuntime

**Files:**
- Modify: `study_task_assistant/knowledge_runtime.py`
- Test: `tests/test_knowledge_runtime.py`

**Interfaces:**
- Produces: `KnowledgeRuntime.document_service()` using the same model and store as retrieval.
- Preserves: `KnowledgeRuntime.executor_factory()` returns a fresh executor per request.

- [ ] Write a failing test proving the model initializes once and the document service shares it with retrieval.
- [ ] Run the runtime tests and confirm the new assertion fails.
- [ ] Refactor lazy initialization to retain model/store/retriever and construct the document service.
- [ ] Run runtime and knowledge-tool tests.

### Task 3: Authenticated HTTP routes

**Files:**
- Modify: `study_task_assistant/schemas.py`
- Modify: `study_task_assistant/api.py`
- Test: `tests/test_document_api.py`

**Interfaces:**
- Produces: `POST /documents`, `GET /documents`, `GET /documents/{id}`, and `DELETE /documents/{id}`.
- Consumes: injected `document_service_factory` or the production `KnowledgeRuntime` service.

- [ ] Write failing API tests for authentication, lifecycle responses, conflict, 404 isolation, and 204 deletion.
- [ ] Run the API tests and confirm the routes are missing.
- [ ] Add Pydantic request/response schemas and route error mappings.
- [ ] Run targeted API tests and the full suite.

### Task 4: Container and real-chain verification

**Files:**
- Modify: `study_task_assistant/DOCKER.md`
- Modify: `学习进度.md`
- Modify: `学习记录/2026-10-01-01.md`

**Interfaces:**
- Verifies: authenticated upload becomes searchable through `/agent/chat`.

- [ ] Build and restart the API image with `docker compose up -d --build api`.
- [ ] Upload a small document through the authenticated API and call `/agent/chat` with a question answered by that document.
- [ ] Confirm the trace contains one knowledge tool execution and the final answer cites the uploaded source.
- [ ] Run the complete pytest suite and record observed results without storing credentials.
