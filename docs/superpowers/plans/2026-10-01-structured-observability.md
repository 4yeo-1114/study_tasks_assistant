# Structured Agent Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add correlated JSON metadata logs across HTTP, Agent model calls, retrieval, and ingestion.

**Architecture:** `observability.py` owns request context and JSON emission. Existing layers emit phase events at their natural boundaries and never pass request IDs manually.

**Tech Stack:** Python logging, ContextVar, FastAPI middleware, perf_counter, pytest.

## Global Constraints

- Do not log prompts, document content, tool arguments, JWTs, API keys, database URLs, or raw provider messages.
- Generate request IDs server-side and return them through `X-Request-ID`.
- Preserve existing public API schemas and Agent behavior.

### Task 1: Request context and HTTP events

- [ ] Write failing tests for JSON emission and HTTP request headers/events.
- [ ] Implement request context helpers and FastAPI middleware.
- [ ] Run observability and API tests.

### Task 2: Agent and retrieval phase metrics

- [ ] Write failing tests for model duration and retrieval cache/candidate telemetry.
- [ ] Instrument Agent trace/model calls and KnowledgeToolExecutor.
- [ ] Run Agent and knowledge tests.

### Task 3: Ingestion metrics and final verification

- [ ] Write a failing ingestion metadata/privacy test.
- [ ] Instrument DocumentService success and failure paths.
- [ ] Run the full suite and verify real container JSON logs.
