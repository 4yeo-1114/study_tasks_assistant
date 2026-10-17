"""Persist model-suggested task writes until the authenticated user confirms."""

import secrets
import time
from collections.abc import Callable
from datetime import date
from typing import Annotated

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from llm.deepseek_api import DeepSeekSettings
from llm.deepseek_tools import ToolCallProposal, request_tool_proposal
from llm.model_client import ModelMessage
from storage.models import Task, TaskProposal
from agent.readonly_tools import ToolArgumentsError
from tasks.repository import _task_to_dict
from web.schemas import TaskPriority, TaskTitle


CREATE_TASK_TOOL: dict[str, object] = {
    "type": "function",
    "function": {
        "name": "create_task",
        "description": "只提出创建学习任务的建议；必须由用户确认后才能写入。",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "非空任务标题"},
                "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                "due_date": {"type": "string", "format": "date", "description": "可选截止日期 YYYY-MM-DD"},
            },
            "required": ["title"],
            "additionalProperties": False,
        },
    },
}


class CreateTaskArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: TaskTitle
    priority: TaskPriority = "medium"
    due_date: date | None = None


class ProposalNotFoundError(LookupError):
    pass


class ProposalExpiredError(ValueError):
    pass


class ProposalConflictError(ValueError):
    pass


#保存 create_task提案
#业务层：管理提案状态和确认事务
class TaskProposalService:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        clock: Callable[[], int | float] = time.time,
    ) -> None:
        self._sessions = sessions
        self._clock = clock

    #从tool_call中获取提案 并加入数据库中
    def propose_from_call(
        self,
        user_id: int,
        call: ToolCallProposal,
        *,
        ttl_seconds: int = 900,
        idempotency_key: str | None = None,
    ) -> dict:
        _validate_user_id(user_id)
        if call.name != "create_task":
            raise ValueError("只能保存 create_task 提案")
        if not isinstance(ttl_seconds, int) or ttl_seconds < 1:
            raise ValueError("提案有效期必须为正整数秒")
        if idempotency_key is not None:
            idempotency_key = idempotency_key.strip()
            if not idempotency_key or len(idempotency_key) > 128:
                raise ValueError("幂等键长度必须为 1 到 128 个字符")
        try:
            #Pydantic校验参数
            arguments = CreateTaskArguments.model_validate(call.arguments)
        except ValidationError as exc:
            raise ToolArgumentsError("create_task 参数校验失败") from exc

        with self._sessions.begin() as session:
            if idempotency_key is not None:
                existing = session.scalar(
                    select(TaskProposal).where(
                        TaskProposal.owner_id == user_id,
                        TaskProposal.idempotency_key == idempotency_key,
                    )
                )
                if existing is not None:
                    same_arguments = (
                        existing.title == arguments.title
                        and existing.priority == arguments.priority
                        and existing.due_date == arguments.due_date
                    )
                    if not same_arguments:
                        raise ProposalConflictError("相同幂等键对应不同提案参数")
                    return _proposal_to_dict(existing)
            proposal = TaskProposal(
                id=secrets.token_urlsafe(24),
                owner_id=user_id,
                title=arguments.title,
                priority=arguments.priority,
                due_date=arguments.due_date,
                expires_at=int(self._clock()) + ttl_seconds,
                status="pending",
                idempotency_key=idempotency_key,
            )
            session.add(proposal)
        return _proposal_to_dict(proposal)

    #通过user_id 和proposal_id来查询提案
    def get(self, user_id: int, proposal_id: str) -> dict:
        _validate_user_id(user_id)
        with self._sessions() as session:
            proposal = _owned_proposal(session, user_id, proposal_id)
            return _proposal_to_dict(proposal)

    def confirm(self, user_id: int, proposal_id: str) -> dict:
        """Claim a pending proposal and create its task in one transaction."""
        _validate_user_id(user_id)
        with self._sessions.begin() as session:
            updated = session.execute(
                update(TaskProposal)
                .where(
                    TaskProposal.id == proposal_id,
                    TaskProposal.owner_id == user_id,
                    TaskProposal.status == "pending",
                    TaskProposal.expires_at > int(self._clock()),
                )
                .values(status="confirmed")
            )
            proposal = _owned_proposal(session, user_id, proposal_id)
            if updated.rowcount == 1:
                task = Task(
                    owner_id=user_id,
                    title=proposal.title,
                    status="pending",
                    priority=proposal.priority,
                    due_date=proposal.due_date,
                )
                session.add(task)
                session.flush()
                proposal.task_id = task.id
                result = _proposal_to_dict(proposal)
                result["task"] = _task_to_dict(task)
                return result
            if proposal.status == "confirmed":
                task = session.get(Task, proposal.task_id)
                result = _proposal_to_dict(proposal)
                result["task"] = _task_to_dict(task) if task is not None else None
                return result
            if proposal.status == "rejected":
                raise ProposalConflictError("提案已拒绝")
            raise ProposalExpiredError("提案已过期")

    def reject(self, user_id: int, proposal_id: str) -> dict:
        _validate_user_id(user_id)
        with self._sessions.begin() as session:
            session.execute(
                update(TaskProposal)
                .where(
                    TaskProposal.id == proposal_id,
                    TaskProposal.owner_id == user_id,
                    TaskProposal.status == "pending",
                )
                .values(status="rejected")
            )
            proposal = _owned_proposal(session, user_id, proposal_id)
            if proposal.status == "confirmed":
                raise ProposalConflictError("提案已确认，不能拒绝")
            return _proposal_to_dict(proposal)

#利用request_tool_proposal 向模型请求创建任务提案
#串联模型提案与提案保存
def propose_task_from_model(
    question: str,
    *,
    user_id: int,
    service: TaskProposalService,
    settings: DeepSeekSettings,
    transport: httpx.BaseTransport | None = None,
) -> dict:
    _validate_user_id(user_id)
    if not question.strip():
        raise ValueError("问题不能为空")
    response = request_tool_proposal(
        [ModelMessage(role="user", content=question)],
        tools=[CREATE_TASK_TOOL],
        settings=settings,
        transport=transport,
    )
    if len(response.calls) != 1:
        raise ValueError("一次只允许一个创建任务提案")
    return service.propose_from_call(user_id, response.calls[0])





def _validate_user_id(user_id: int) -> None:
    if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id < 1:
        raise ValueError("可信 user_id 必须是正整数")


def _owned_proposal(session: Session, user_id: int, proposal_id: str) -> TaskProposal:
    proposal = session.scalar(
        select(TaskProposal).where(
            TaskProposal.id == proposal_id,
            TaskProposal.owner_id == user_id,
        )
    )
    if proposal is None:
        raise ProposalNotFoundError("找不到提案")
    return proposal


def _proposal_to_dict(proposal: TaskProposal) -> dict:
    return {
        "id": proposal.id,
        "title": proposal.title,
        "priority": proposal.priority,
        "due_date": proposal.due_date.isoformat() if proposal.due_date else None,
        "expires_at": proposal.expires_at,
        "status": proposal.status,
        "task_id": proposal.task_id,
    }
