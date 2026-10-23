"""Real PostgreSQL acceptance; never target the application database."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.engine import make_url

from agent.plan_approval import PlanApprovalWorkflow
from agent.persistent_runtime import create_checkpoint_store
from agent.agent_loop import AgentAnswer
from agent.session_store import AgentSessionStore
from storage.database import Database
from storage.migration import upgrade_database
from tests.test_postgres_integration import _reset_database
from tests.test_weekly_plan_api import _payload, _profile, _week_start
from web.api import create_app
from web.schemas import WeeklyPlanCreate
from weekly_plans.service import WeeklyPlanConflictError, WeeklyPlanService


@pytest.fixture
def pg_runtime():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("需要 TEST_DATABASE_URL 指向 pgvector 的 study_tasks_test")
    if make_url(url).database != "study_tasks_test":
        pytest.fail("只允许 study_tasks_test 独立测试库")
    database = Database(url)
    _reset_database(database)
    upgrade_database(url)
    try:
        with TestClient(create_app(url, token_secret="postgres-test-secret-at-least-32-bytes")) as client:
            client.post("/auth/register", json={"username": "pg_agent", "password": "pg-agent-password-123"})
            token = client.post("/auth/login", data={"username": "pg_agent", "password": "pg-agent-password-123"}).json()["access_token"]
            client.headers.update({"Authorization": f"Bearer {token}"})
            assert _profile(client)["revision"] == 1
            yield database, client, WeeklyPlanService(database.sessions)
    finally:
        _reset_database(database)
        database.dispose()


def test_postgres_checkpoint_interrupt_survives_connection_reopen(pg_runtime):
    database, client, service = pg_runtime
    plan = client.post("/plans/weekly", json=_payload(_week_start())).json()
    assert [item["id"] for item in client.get("/plans").json()] == [plan["id"]]
    # The API has already paused this plan in the PostgreSQL saver.
    store = create_checkpoint_store(database.url)
    try:
        flow = PlanApprovalWorkflow(service, store.saver)
        config = flow._config(1, plan["id"])
        assert flow._graph.get_state(config).next == ("review",)
        assert flow.wait(1, plan["id"])["waiting_for_confirmation"] is True
    finally:
        store.close()
    store = create_checkpoint_store(database.url)
    try:
        flow = PlanApprovalWorkflow(service, store.saver)
        assert flow.decide(1, plan["id"], "confirm")["status"] == "confirmed"
        assert flow._graph.get_state(config).next == ()
        assert len(client.get("/tasks").json()) == 2
        with database.engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0017_agent_message_sequence"
    finally:
        store.close()


@pytest.mark.parametrize("same_plan", [True, False], ids=["repeat-confirm", "version-race"])
def test_postgres_confirmation_row_lock_prevents_duplicate_or_stale_writes(pg_runtime, same_plan):
    _, client, service = pg_runtime
    first = client.post("/plans/weekly", json=_payload(_week_start())).json()
    second = first if same_plan else client.post("/plans/weekly", json=_payload(_week_start(), "second")).json()
    barrier = Barrier(2)

    def confirm(plan):
        barrier.wait(timeout=10)
        try:
            return service.confirm(1, plan["id"])["status"]
        except WeeklyPlanConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(confirm, [first, second]))
    assert sorted(results) == (["confirmed", "confirmed"] if same_plan else ["confirmed", "conflict"])
    assert len(client.get("/tasks").json()) == 2
    assert client.get("/profile").json()["plan_version"] == 1


def test_postgres_confirmation_failure_rolls_back_whole_batch_and_resume_retries(pg_runtime):
    database, client, service = pg_runtime
    plan = client.post("/plans/weekly", json=_payload(_week_start())).json()
    # Crash after both task INSERTs, before the plan/profile update commits.
    def fail_update(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE USER_PROFILES"):
            raise RuntimeError("injected confirmation failure")

    store = create_checkpoint_store(database.url)
    try:
        flow = PlanApprovalWorkflow(service, store.saver)
        event.listen(database.engine, "before_cursor_execute", fail_update)
        try:
            with pytest.raises(RuntimeError, match="injected"):
                flow.decide(1, plan["id"], "confirm")
        finally:
            event.remove(database.engine, "before_cursor_execute", fail_update)
        assert service.get(1, plan["id"])["status"] == "pending"
        assert client.get("/tasks").json() == []
        assert client.get("/profile").json()["plan_version"] == 0
        assert flow.decide(1, plan["id"], "confirm")["status"] == "confirmed"
        assert len(client.get("/tasks").json()) == 2
    finally:
        store.close()


def test_postgres_concurrent_adjustment_reuses_one_proposal(pg_runtime):
    _, client, service = pg_runtime
    plan = client.post("/plans/weekly", json=_payload(_week_start())).json()
    service.confirm(1, plan["id"])
    barrier = Barrier(2)

    def adjust(_):
        barrier.wait(timeout=10)
        return service.adjust(1, plan["id"], "pg-adjust-once")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(adjust, range(2)))
    assert results[0][0]["id"] == results[1][0]["id"]
    assert sorted(result[1] for result in results) == [False, True]
    assert len(client.get("/tasks").json()) == 2


def test_postgres_concurrent_weekly_create_reuses_same_idempotency_key(pg_runtime):
    database, client, service = pg_runtime
    request = WeeklyPlanCreate.model_validate(_payload(_week_start(), "pg-create-race"))
    barrier = Barrier(2)

    def meet_before_insert(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO WEEKLY_PLANS"):
            barrier.wait(timeout=10)

    event.listen(database.engine, "before_cursor_execute", meet_before_insert)

    def create(_):
        barrier.wait(timeout=10)
        return service.create(1, request)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            plans = list(pool.map(create, range(2)))
    finally:
        event.remove(database.engine, "before_cursor_execute", meet_before_insert)
    assert plans[0]["id"] == plans[1]["id"]
    assert plans[0]["status"] == plans[1]["status"] == "pending"
    with service._sessions() as session:
        assert session.scalar(text("SELECT count(*) FROM weekly_plans WHERE idempotency_key = 'pg-create-race'")) == 1


def test_postgres_concurrent_run_completion_allocates_distinct_message_sequences(pg_runtime):
    database, _, _ = pg_runtime
    sessions = AgentSessionStore(database.sessions)
    conversation = sessions.open(1, None)
    runs = [sessions.start_run(1, conversation["id"]) for _ in range(2)]
    barrier = Barrier(2)

    def meet_after_sequence_read(connection, cursor, statement, parameters, context, executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("update agent_sessions") and "message_sequence" in normalized:
            barrier.wait(timeout=10)

    event.listen(database.engine, "before_cursor_execute", meet_after_sequence_read)

    def complete(index):
        barrier.wait(timeout=10)
        sessions.complete_run(1, conversation["id"], runs[index]["id"], f"q{index}",
                              AgentAnswer(answer=f"a{index}", model_steps=1, tool_calls=0))

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(complete, range(2)))
    finally:
        event.remove(database.engine, "before_cursor_execute", meet_after_sequence_read)
    detail = sessions.detail(1, conversation["id"])
    assert [message["sequence"] for message in detail["messages"]] == [1, 2, 3, 4]
    assert len({message["sequence"] for message in detail["messages"]}) == 4
