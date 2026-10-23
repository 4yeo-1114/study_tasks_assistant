from __future__ import annotations

import hashlib
import json
import secrets
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from storage.models import Task, UserProfile, WeeklyPlan, WorkoutSession


class WeeklyPlanNotFoundError(LookupError):
    pass


class WeeklyPlanConflictError(ValueError):
    pass


class WeeklyPlanValidationError(ValueError):
    pass


def _task_read(task: Task) -> dict[str, Any]:
    return {"id": task.id, "title": task.title, "status": task.status, "priority": task.priority,
            "due_date": task.due_date, "task_type": task.task_type,
            "estimated_minutes": task.estimated_minutes, "actual_minutes": task.actual_minutes}


def _plan_read(plan: WeeklyPlan, tasks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"id": plan.id, "week_start": plan.week_start,
            "expected_profile_revision": plan.expected_profile_revision,
            "base_plan_version": plan.base_plan_version, "status": plan.status,
            "plan_version": plan.plan_version, "tasks": tasks if tasks is not None else plan.task_snapshot,
            "plan_kind": plan.plan_kind, "source_plan_id": plan.source_plan_id,
            "adjustment_summary": plan.adjustment_summary,
            "created_at": plan.created_at}


class WeeklyPlanService:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    @staticmethod
    def _validate(profile: UserProfile, request: Any) -> None:
        by_day: dict[Any, int] = {}
        fitness_days: set[Any] = set()
        for task in request.tasks:
            by_day[task.due_date] = by_day.get(task.due_date, 0) + task.estimated_minutes
            if task.task_type == "fitness":
                fitness_days.add(task.due_date)
        if profile.daily_minutes is not None and any(total > profile.daily_minutes for total in by_day.values()):
            raise WeeklyPlanValidationError("每日预算不能超过档案中的 daily_minutes")
        if profile.training_days_per_week is not None and len(fitness_days) > profile.training_days_per_week:
            raise WeeklyPlanValidationError("训练日期数不能超过每周训练频次")

    @staticmethod
    def _hash(request: Any) -> str:
        return hashlib.sha256(json.dumps(request.model_dump(mode="json"), sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def create(self, owner_id: int, request: Any) -> dict[str, Any]:
        payload_hash = self._hash(request)
        with self._sessions.begin() as session:
            existing = session.scalar(select(WeeklyPlan).where(WeeklyPlan.owner_id == owner_id, WeeklyPlan.idempotency_key == request.idempotency_key))
            if existing is not None:
                if existing.payload_hash != payload_hash:
                    raise WeeklyPlanConflictError("同一幂等键不能对应不同提案")
                return _plan_read(existing)
            profile = session.scalar(select(UserProfile).where(UserProfile.owner_id == owner_id))
            if profile is None:
                raise WeeklyPlanValidationError("创建计划前需要用户档案")
            if profile.revision != request.expected_profile_revision:
                raise WeeklyPlanConflictError("档案已更新，请基于最新档案重新生成计划")
            self._validate(profile, request)
            snapshot = [task.model_dump(mode="json") | {"status": "pending", "priority": "medium", "actual_minutes": None} for task in request.tasks]
            plan = WeeklyPlan(id=secrets.token_hex(16), owner_id=owner_id, week_start=request.week_start,
                              expected_profile_revision=request.expected_profile_revision, base_plan_version=request.base_plan_version,
                              idempotency_key=request.idempotency_key, payload_hash=payload_hash, task_snapshot=snapshot,
                              status="pending", task_ids=[], plan_kind="weekly", created_at=datetime.utcnow())
            try:
                with session.begin_nested():
                    session.add(plan)
                    session.flush()
                return _plan_read(plan)
            except IntegrityError:
                # A concurrent request may have won the unique idempotency key
                # after our initial lookup. Roll back only the insert savepoint,
                # then return the winner if its payload is equivalent.
                existing = session.scalar(select(WeeklyPlan).where(
                    WeeklyPlan.owner_id == owner_id,
                    WeeklyPlan.idempotency_key == request.idempotency_key,
                ))
                if existing is None:
                    raise
                if existing.payload_hash != payload_hash:
                    raise WeeklyPlanConflictError("同一幂等键不能对应不同提案")
                return _plan_read(existing)

    def adjust(self, owner_id: int, source_plan_id: str, idempotency_key: str) -> tuple[dict[str, Any], bool]:
        with self._sessions.begin() as session:
            source = session.scalar(select(WeeklyPlan).where(
                WeeklyPlan.id == source_plan_id, WeeklyPlan.owner_id == owner_id,
            ).with_for_update())
            if source is None:
                raise WeeklyPlanNotFoundError("找不到计划")
            if source.status != "confirmed":
                raise WeeklyPlanConflictError("只能调整已确认的计划")
            payload = {"source_plan_id": source.id, "idempotency_key": idempotency_key}
            payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            existing = session.scalar(select(WeeklyPlan).where(
                WeeklyPlan.owner_id == owner_id, WeeklyPlan.idempotency_key == idempotency_key,
            ))
            if existing is not None:
                if existing.payload_hash != payload_hash:
                    raise WeeklyPlanConflictError("同一幂等键不能对应不同调整")
                return _plan_read(existing), False

            profile = session.scalar(select(UserProfile).where(UserProfile.owner_id == owner_id))
            if profile is None:
                raise WeeklyPlanValidationError("创建计划前需要用户档案")
            source_tasks = session.scalars(select(Task).where(
                Task.owner_id == owner_id, Task.id.in_(source.task_ids),
            ).order_by(Task.id)).all()
            completed_count = sum(task.status == "completed" for task in source_tasks)
            pending = [task for task in source_tasks if task.status == "pending"]
            if not pending:
                raise WeeklyPlanValidationError("原计划没有未完成任务，无需生成调整提案")
            next_week = source.week_start + timedelta(days=7)
            workouts_count = session.scalar(select(func.count(WorkoutSession.id)).where(
                WorkoutSession.owner_id == owner_id,
                WorkoutSession.workout_date >= source.week_start,
                WorkoutSession.workout_date < next_week,
            )) or 0
            snapshot = [{
                "title": task.title, "task_type": task.task_type,
                "due_date": (task.due_date + timedelta(days=7)).isoformat(),
                "estimated_minutes": task.estimated_minutes,
                "status": "pending", "priority": task.priority, "actual_minutes": None,
            } for task in pending]
            request_like = SimpleNamespace(tasks=[SimpleNamespace(**item) for item in snapshot])
            self._validate(profile, request_like)
            summary = (
                f"Completed tasks excluded: {completed_count}; pending tasks carried forward: {len(pending)}; "
                f"shifted days: 7; workout sessions in source week: {workouts_count} "
                "(evidence only; no task completion inferred)."
            )
            plan = WeeklyPlan(
                id=secrets.token_hex(16), owner_id=owner_id, week_start=source.week_start + timedelta(days=7),
                expected_profile_revision=profile.revision, base_plan_version=profile.plan_version,
                idempotency_key=idempotency_key, payload_hash=payload_hash, task_snapshot=snapshot,
                status="pending", task_ids=[], plan_kind="adjustment", source_plan_id=source.id,
                adjustment_summary=summary, created_at=datetime.utcnow(),
            )
            session.add(plan)
            session.flush()
            return _plan_read(plan), True

    def get(self, owner_id: int, plan_id: str) -> dict[str, Any]:
        with self._sessions() as session:
            plan = session.scalar(select(WeeklyPlan).where(WeeklyPlan.id == plan_id, WeeklyPlan.owner_id == owner_id))
            if plan is None:
                raise WeeklyPlanNotFoundError("找不到计划提案")
            tasks = plan.task_snapshot
            if plan.status == "confirmed":
                records = session.scalars(select(Task).where(Task.owner_id == owner_id, Task.id.in_(plan.task_ids)).order_by(Task.id)).all()
                tasks = [_task_read(task) for task in records]
            return _plan_read(plan, tasks)

    def list_recent(self, owner_id: int, limit: int = 50) -> list[dict[str, Any]]:
        with self._sessions() as session:
            plans = session.scalars(
                select(WeeklyPlan)
                .where(WeeklyPlan.owner_id == owner_id)
                .order_by(WeeklyPlan.created_at.desc(), WeeklyPlan.id.desc())
                .limit(limit)
            ).all()
            return [_plan_read(plan) for plan in plans]

    def current(self, owner_id: int, week_start: Any) -> dict[str, Any]:
        with self._sessions() as session:
            plan = session.scalar(select(WeeklyPlan).where(WeeklyPlan.owner_id == owner_id, WeeklyPlan.week_start == week_start, WeeklyPlan.status == "confirmed").order_by(WeeklyPlan.plan_version.desc()))
            if plan is None:
                raise WeeklyPlanNotFoundError("该周没有已确认计划")
            records = session.scalars(select(Task).where(Task.owner_id == owner_id, Task.id.in_(plan.task_ids)).order_by(Task.id)).all()
            return _plan_read(plan, [_task_read(task) for task in records])

    def confirm(self, owner_id: int, plan_id: str) -> dict[str, Any]:
        with self._sessions.begin() as session:
            plan = session.scalar(select(WeeklyPlan).where(WeeklyPlan.id == plan_id, WeeklyPlan.owner_id == owner_id).with_for_update())
            if plan is None:
                raise WeeklyPlanNotFoundError("找不到计划提案")
            if plan.status == "rejected":
                raise WeeklyPlanConflictError("已拒绝的提案不能确认")
            if plan.status == "confirmed":
                records = session.scalars(select(Task).where(Task.owner_id == owner_id, Task.id.in_(plan.task_ids)).order_by(Task.id)).all()
                return _plan_read(plan, [_task_read(task) for task in records])
            profile = session.scalar(select(UserProfile).where(UserProfile.owner_id == owner_id).with_for_update())
            if profile is None or profile.revision != plan.expected_profile_revision:
                raise WeeklyPlanConflictError("档案已更新，请重新生成计划")
            if profile.plan_version != plan.base_plan_version:
                raise WeeklyPlanConflictError("计划版本已更新，请重新生成计划")
            created: list[Task] = []
            for item in plan.task_snapshot:
                task = Task(owner_id=owner_id, title=item["title"], status="pending", priority=item["priority"],
                            due_date=date.fromisoformat(item["due_date"]), task_type=item["task_type"], estimated_minutes=item["estimated_minutes"])
                session.add(task)
                created.append(task)
            session.flush()
            profile.plan_version += 1
            plan.status = "confirmed"
            plan.plan_version = profile.plan_version
            plan.task_ids = [task.id for task in created]
            return _plan_read(plan, [_task_read(task) for task in created])

    def reject(self, owner_id: int, plan_id: str) -> dict[str, Any]:
        with self._sessions.begin() as session:
            plan = session.scalar(select(WeeklyPlan).where(WeeklyPlan.id == plan_id, WeeklyPlan.owner_id == owner_id).with_for_update())
            if plan is None:
                raise WeeklyPlanNotFoundError("找不到计划提案")
            if plan.status == "confirmed":
                raise WeeklyPlanConflictError("已确认的计划不能拒绝")
            plan.status = "rejected"
            return _plan_read(plan)
