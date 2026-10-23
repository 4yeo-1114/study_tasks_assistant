"""LangGraph execution with a database-backed checkpoint saver."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypedDict
from urllib.parse import unquote, urlparse

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from agent.agent_loop import AgentAnswer, AgentState, AgentTraceEvent


class PersistentAgentState(TypedDict):
    result: dict


@dataclass
class CheckpointStore:
    saver: BaseCheckpointSaver
    _close: Callable[[], None]

    def close(self) -> None:
        self._close()


def create_checkpoint_store(database_url: str | Path) -> CheckpointStore:
    """Create and initialize a durable saver for the application's database."""
    url = str(database_url)
    if "://" not in url:
        url = f"sqlite+pysqlite:///{Path(url).resolve().as_posix()}"
    if url.startswith("sqlite"):
        parsed = urlparse(url)
        path = unquote(parsed.path)
        if parsed.netloc:
            path = f"//{parsed.netloc}{path}"
        if path == "/:memory:":
            sqlite_path = ":memory:"
        else:
            sqlite_path = path.lstrip("/") if len(path) > 3 and path[2] == ":" else path
        connection = sqlite3.connect(sqlite_path, check_same_thread=False)
        saver = SqliteSaver(connection)
        saver.setup()
        return CheckpointStore(saver, connection.close)

    if url.startswith("postgresql+"):
        url = url.replace("postgresql+psycopg://", "postgresql://", 1)
    if not url.startswith("postgresql://"):
        raise ValueError("checkpoint 仅支持 SQLite 或 PostgreSQL 数据库")
    from psycopg import Connection

    connection = Connection.connect(url, autocommit=True, prepare_threshold=0)
    saver = PostgresSaver(connection)
    saver.setup()
    return CheckpointStore(saver, connection.close)


def run_agent_graph(
    execute: Callable[[], AgentAnswer],
    *,
    checkpointer: BaseCheckpointSaver | None = None,
    thread_id: str | None = None,
) -> AgentAnswer:
    if checkpointer is not None and not thread_id:
        raise ValueError("thread_id 是持久 checkpoint 的必填项")

    def execute_agent(_: PersistentAgentState) -> PersistentAgentState:
        answer = execute()
        return {"result": {
            "answer": answer.answer,
            "model_steps": answer.model_steps,
            "tool_calls": answer.tool_calls,
            "total_tokens": answer.total_tokens,
            "trace": [
                {"run_id": event.run_id, "step": event.step, "state": event.state.value,
                 "event": event.event, "tool_call_id": event.tool_call_id,
                 "proposal_id": event.proposal_id, "attempt": event.attempt,
                 "tool_name": event.tool_name}
                for event in answer.trace
            ],
        }}

    graph = StateGraph(PersistentAgentState)
    graph.add_node("execute_agent", execute_agent)
    graph.add_edge(START, "execute_agent")
    graph.add_edge("execute_agent", END)
    compiled = graph.compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": thread_id}} if checkpointer is not None else None
    result = compiled.invoke({}, config=config)
    payload = result["result"]
    return AgentAnswer(
        answer=payload["answer"],
        model_steps=payload["model_steps"],
        tool_calls=payload["tool_calls"],
        total_tokens=payload.get("total_tokens", 0),
        trace=tuple(
            AgentTraceEvent(
                run_id=item["run_id"], step=item["step"], state=AgentState(item["state"]),
                event=item["event"], tool_call_id=item.get("tool_call_id"),
                proposal_id=item.get("proposal_id"), attempt=item.get("attempt"),
                tool_name=item.get("tool_name"),
            )
            for item in payload.get("trace", ())
        ),
    )
