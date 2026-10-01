# Authenticated Document API Design

## Goal

Expose the existing document ingestion and lifecycle capabilities through authenticated HTTP endpoints so a user can upload text, rebuild it as a new version, inspect lifecycle state, delete a version, and then retrieve it through `/agent/chat`.

## API Contract

- `POST /documents` accepts `source`, `content`, `document_version`, `chunk_size`, and `overlap` as JSON. A new version rebuild uses the same endpoint with a different `document_version`.
- `GET /documents` lists only the authenticated user's document versions, newest first.
- `GET /documents/{document_id}` returns one version only when it belongs to the authenticated user.
- `DELETE /documents/{document_id}` atomically deletes that version's vector chunks and marks its lifecycle row deleted. It returns HTTP 204 and is idempotent for an already deleted version.
- `owner_id` is never accepted from request data; it always comes from JWT authentication.

## Architecture

`DocumentService` is the application boundary. It owns `DocumentLifecycle`, `PgVectorStore`, the shared embedding model, and the session factory. FastAPI validates HTTP payloads and maps service exceptions to HTTP status codes. `KnowledgeRuntime` lazily initializes the shared model/store and provides both request-scoped knowledge executors and the shared document service.

The API is enabled only when the production RAG runtime is configured. SQLite unit tests inject a fake document service factory, while PostgreSQL integration uses the real runtime.

## Data Flow

Upload/rebuild:

1. JWT dependency derives trusted `owner_id`.
2. Pydantic validates source, version, content, chunk size, and overlap.
3. `DocumentService.ingest()` calls the existing lifecycle-aware `ingest_document()`.
4. Lifecycle records pending/processing, chunks are encoded and inserted in one transaction, then the new version becomes ready and active.
5. If encoding or insertion fails, the new version becomes failed and the previous ready version remains active.

Read/delete:

1. Every document query includes both `document_id` and trusted `owner_id` in SQL.
2. A missing or foreign document returns the same 404 response.
3. Delete locks the owner-scoped lifecycle row and removes only its matching vector version in the same transaction.

## Errors

- Invalid request shape: 422.
- Same owner/source/version with different content: 409.
- Missing or foreign document: 404.
- RAG runtime/model unavailable: 503.
- Unexpected ingestion/storage failure: 500, without leaking document content or credentials.

## Verification

Automated tests cover owner isolation, idempotent same-content upload, version conflict, upload/list/get/delete routes, and runtime reuse. A real Compose check uploads one document and confirms `/agent/chat` retrieves evidence from it.
