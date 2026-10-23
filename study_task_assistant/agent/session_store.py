"""Database-backed session and run records for persistent agent conversations."""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from agent.agent_loop import AgentAnswer
from storage.models import AgentMessage, AgentRun, AgentSession


class AgentSessionNotFoundError(LookupError):
    pass


class AgentSessionStore:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def open(self, owner_id: int, session_id: str | None) -> dict[str, Any]:
        now = _utc_now()
        with self._sessions.begin() as session:
            if session_id is not None:
                record = session.scalar(
                    select(AgentSession).where(
                        AgentSession.id == session_id,
                        AgentSession.owner_id == owner_id,
                        AgentSession.status == "active",
                    )
                )
                if record is None:
                    raise AgentSessionNotFoundError("找不到可恢复的会话")
                record.updated_at = now
            else:
                record = AgentSession(
                    id=uuid.uuid4().hex,
                    owner_id=owner_id,
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
            session.flush()
            return _session_to_dict(record)

    def start_run(self, owner_id: int, session_id: str) -> dict[str, Any]:
        now = _utc_now()
        with self._sessions.begin() as session:
            self._owned_active_session(session, owner_id, session_id)
            run = AgentRun(
                id=uuid.uuid4().hex,
                session_id=session_id,
                owner_id=owner_id,
                status="running",
                started_at=now,
            )
            session.add(run)
            session.flush()
            return _run_to_dict(run)

    def complete_run(
        self,
        owner_id: int,
        session_id: str,
        run_id: str,
        question: str,
        answer: AgentAnswer,
    ) -> None:
        now = _utc_now()
        with self._sessions.begin() as session:
            conversation = self._owned_active_session(session, owner_id, session_id)
            run = self._owned_run(session, owner_id, session_id, run_id)
            if run.status != "running":
                raise ValueError("Agent 运行状态不可再次完成")
            last_sequence = session.scalar(
                update(AgentSession)
                .where(
                    AgentSession.id == session_id,
                    AgentSession.owner_id == owner_id,
                    AgentSession.status == "active",
                )
                .values(message_sequence=AgentSession.message_sequence + 2, updated_at=now)
                .returning(AgentSession.message_sequence)
            )
            if last_sequence is None:
                raise AgentSessionNotFoundError("找不到可恢复的会话")
            sequence = last_sequence - 1
            session.add_all((
                AgentMessage(
                    session_id=session_id,
                    sequence=sequence,
                    role="user",
                    content=question,
                    created_at=now,
                ),
                AgentMessage(
                    session_id=session_id,
                    sequence=sequence + 1,
                    role="assistant",
                    content=answer.answer,
                    created_at=now,
                ),
            ))
            run.status = "succeeded"
            run.completed_at = now

    def fail_run(self, owner_id: int, session_id: str, run_id: str, error: Exception) -> None:
        now = _utc_now()
        with self._sessions.begin() as session:
            run = self._owned_run(session, owner_id, session_id, run_id)
            if run.status == "running":
                run.status = "failed"
                run.error_type = type(error).__name__
                run.completed_at = now

    def detail(self, owner_id: int, session_id: str) -> dict[str, Any]:
        with self._sessions() as session:
            conversation = self._owned_active_session(session, owner_id, session_id)
            messages = session.scalars(
                select(AgentMessage)
                .where(AgentMessage.session_id == session_id)
                .order_by(AgentMessage.sequence)
            ).all()
            runs = session.scalars(
                select(AgentRun)
                .where(AgentRun.owner_id == owner_id, AgentRun.session_id == session_id)
                .order_by(AgentRun.started_at)
            ).all()
            return {
                **_session_to_dict(conversation),
                "messages": [_message_to_dict(message) for message in messages],
                "runs": [_run_to_dict(run) for run in runs],
            }

    @staticmethod
    def _owned_active_session(session: Session, owner_id: int, session_id: str) -> AgentSession:
        record = session.scalar(
            select(AgentSession).where(
                AgentSession.id == session_id,
                AgentSession.owner_id == owner_id,
                AgentSession.status == "active",
            )
        )
        if record is None:
            raise AgentSessionNotFoundError("找不到可恢复的会话")
        return record

    @staticmethod
    def _owned_run(session: Session, owner_id: int, session_id: str, run_id: str) -> AgentRun:
        run = session.scalar(
            select(AgentRun).where(
                AgentRun.id == run_id,
                AgentRun.owner_id == owner_id,
                AgentRun.session_id == session_id,
            )
        )
        if run is None:
            raise AgentSessionNotFoundError("找不到会话运行记录")
        return run


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _session_to_dict(record: AgentSession) -> dict[str, Any]:
    return {"id": record.id, "status": record.status}


def _run_to_dict(record: AgentRun) -> dict[str, Any]:
    return {
        "id": record.id,
        "status": record.status,
        "error_type": record.error_type,
    }


def _message_to_dict(record: AgentMessage) -> dict[str, Any]:
    return {"sequence": record.sequence, "role": record.role, "content": record.content}
