# Structured Agent Observability Design

## Goal

Produce correlated, machine-readable metadata logs for HTTP, Agent model calls, knowledge retrieval, and document ingestion without logging prompts, document content, credentials, or raw provider errors.

## Correlation

- One server-generated `request_id` identifies an HTTP request and is returned in `X-Request-ID`.
- One `agent_run_id` identifies the Agent loop inside that request.
- `step` and retry `attempt` identify model operations inside the run.
- `tool_call_id` identifies one model-proposed tool invocation.
- A `ContextVar` propagates request_id through synchronous route, Agent, retrieval, and service calls without changing every function signature.

## Events

- `http_request_completed/failed`: method, path, status, duration.
- `agent_trace`: run, step, state, event, call ID, attempt.
- `model_request_completed/failed`: run, step, duration, error type.
- `knowledge_retrieval_completed/failed`: call ID, cache hit, candidate count, duration, error type.
- `document_ingestion_completed/failed`: document ID when available, state, chunk count, duration, error type.

All log messages are compact JSON. Allowed values are controlled metadata. Questions, arguments, content, authorization headers, API keys, JWTs, database URLs, and raw provider messages are excluded.

## Verification

Tests parse emitted JSON, verify correlation fields and phase metrics, check cache telemetry, and assert representative secrets and content never occur in logs.
