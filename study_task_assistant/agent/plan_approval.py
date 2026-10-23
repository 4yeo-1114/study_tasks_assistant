"""Durable human approval for weekly plans; SQL remains the business authority.

Interrupt nodes restart on resume, so they must contain no business writes.
The following apply node delegates to the transactional, idempotent plan service.
"""

from threading import RLock
from typing import TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from weekly_plans.service import WeeklyPlanConflictError, WeeklyPlanService


class ApprovalState(TypedDict):
    owner_id: int
    plan_id: str
    decision: str
    status: str


class PlanApprovalWorkflow:
    def __init__(self, service: WeeklyPlanService, saver: BaseCheckpointSaver):
        self._service = service
        # Serialize graph operations in this app. Cross-process business safety
        # still relies on SQL row locks/version checks, not this Python lock.
        self._lock = RLock()
        graph = StateGraph(ApprovalState)
        graph.add_node("review", self._review)
        graph.add_node("apply", self._apply)
        graph.add_edge(START, "review")
        graph.add_edge("review", "apply")
        graph.add_edge("apply", END)
        self._graph = graph.compile(checkpointer=saver)

    @staticmethod
    def _config(owner_id: int, plan_id: str):
        return {"configurable": {"thread_id": f"plan-approval-v1:{owner_id}:{plan_id}"}}

    @staticmethod
    def _review(state: ApprovalState):
        decision = interrupt({"plan_id": state["plan_id"], "action": "confirm_or_reject"})
        if decision not in ("confirm", "reject"):
            raise ValueError("decision 必须是 confirm 或 reject")
        return {"decision": decision}

    def _apply(self, state: ApprovalState):
        operation = self._service.confirm if state["decision"] == "confirm" else self._service.reject
        plan = operation(state["owner_id"], state["plan_id"])
        return {"status": plan["status"]}

    def wait(self, owner_id: int, plan_id: str) -> dict:
        with self._lock:
            # Authorize before accessing any checkpoint. IDs never come from a model.
            plan = self._service.get(owner_id, plan_id)
            config = self._config(owner_id, plan_id)
            if plan["status"] == "pending" and not self._graph.get_state(config).values:
                self._graph.invoke({"owner_id": owner_id, "plan_id": plan_id}, config)
            return {"plan_id": plan_id, "status": plan["status"],
                    "waiting_for_confirmation": plan["status"] == "pending"}

    def decide(self, owner_id: int, plan_id: str, decision: str) -> dict:
        if decision not in ("confirm", "reject"):
            raise ValueError("decision 必须是 confirm 或 reject")
        with self._lock:
            plan = self._service.get(owner_id, plan_id)
            operation = self._service.confirm if decision == "confirm" else self._service.reject
            if plan["status"] != "pending":
                # SQL may have committed before a checkpoint write failed. Return
                # the authoritative idempotent result, or the opposite-action conflict.
                return operation(owner_id, plan_id)
            self.wait(owner_id, plan_id)
            config = self._config(owner_id, plan_id)
            snapshot = self._graph.get_state(config)
            saved_decision = snapshot.values.get("decision")
            if saved_decision is not None and saved_decision != decision:
                if decision != "reject":
                    raise WeeklyPlanConflictError("该工作流已有不同决定，请重新生成提案")
                # A stale confirmation may fail while SQL remains pending. An
                # explicit rejection must still be possible; replay apply with
                # the new decision. SQL locking resolves concurrent decisions.
                self._graph.update_state(config, {"decision": "reject"}, as_node="review")
            # None retries a failed apply node; Command resumes only the review interrupt.
            command = None if saved_decision is not None else Command(resume=decision)
            self._graph.invoke(command, config)
            return self._service.get(owner_id, plan_id)
