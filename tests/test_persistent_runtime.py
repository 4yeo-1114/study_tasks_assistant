from pathlib import Path

from agent.agent_loop import AgentAnswer
from agent.persistent_runtime import (
    create_checkpoint_store,
    run_agent_graph,
)


def test_sqlite_checkpoint_survives_store_reopen(tmp_path):
    path = tmp_path / "checkpoints.db"
    store = create_checkpoint_store(f"sqlite+pysqlite:///{path.as_posix()}")
    try:
        result = run_agent_graph(
            lambda: AgentAnswer("第一次执行", 1, 0),
            checkpointer=store.saver,
            thread_id="session-a",
        )
        assert result.answer == "第一次执行"
        assert store.saver.get_tuple({"configurable": {"thread_id": "session-a"}}) is not None
        assert store.saver.get_tuple({"configurable": {"thread_id": "session-b"}}) is None
    finally:
        store.close()

    reopened = create_checkpoint_store(f"sqlite+pysqlite:///{path.as_posix()}")
    try:
        checkpoint = reopened.saver.get_tuple({"configurable": {"thread_id": "session-a"}})
        assert checkpoint is not None
        assert checkpoint.checkpoint["channel_values"]["result"]["answer"] == "第一次执行"
    finally:
        reopened.close()


def test_checkpoint_requires_thread_id():
    store = create_checkpoint_store("sqlite+pysqlite:///:memory:")
    try:
        try:
            run_agent_graph(lambda: AgentAnswer("x", 1, 0), checkpointer=store.saver)
        except ValueError as exc:
            assert "thread_id" in str(exc)
        else:
            raise AssertionError("missing thread_id should fail")
    finally:
        store.close()
