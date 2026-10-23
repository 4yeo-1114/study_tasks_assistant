"""Plan-only model tools. Identity, versions and authorization stay server-side."""

import hashlib
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent.readonly_tools import ToolArgumentsError, ToolExecutionResult
from user_profile.repository import UserProfileNotFoundError
from web.schemas import WeeklyPlanCreate, WeeklyPlanRead, WeeklyPlanTask


class WeeklyPlanArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    week_start: date
    tasks: list[WeeklyPlanTask] = Field(min_length=1, max_length=100)


class AdjustmentArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_plan_id: str = Field(min_length=1, max_length=32)


def _tool(name, description, schema):
    return {"type": "function", "function": {"name": name, "description": description, "parameters": schema}}


PLANNING_TOOLS = [
    _tool("get_planning_context", "只读当前用户显式档案、任务完成统计和训练进步。生成计划前必须调用；资料不足应向用户澄清。",
          {"type": "object", "properties": {}, "additionalProperties": False}),
    _tool("propose_weekly_plan", "根据显式档案提出周计划，仅保存待确认提案，不创建正式任务；日期和预算由服务端校验。",
          WeeklyPlanArguments.model_json_schema()),
    _tool("propose_plan_adjustment", "根据真实完成和训练记录提出已有计划的下周调整，必须另行由用户确认。",
          AdjustmentArguments.model_json_schema()),
]


class PlanningToolExecutor:
    def __init__(self, *, profiles, plans, approval, tasks, fitness, request_key: str):
        self._profiles, self._plans, self._approval = profiles, plans, approval
        self._tasks, self._fitness = tasks, fitness
        self._request_key = request_key
        self._profile = None

    def execute(self, call, *, owner_id: int):
        try:
            if call.name == "get_planning_context":
                if call.arguments:
                    raise ToolArgumentsError("get_planning_context 不接受参数")
                try:
                    self._profile = self._profiles.get(owner_id)
                except UserProfileNotFoundError:
                    self._profile = None
                output = {"profile": self._profile, "needs_profile": self._profile is None,
                          "task_progress": self._tasks.progress(owner_id),
                          "fitness_progress": self._fitness.progress(owner_id),
                          "today": date.today().isoformat(),
                          "limitations": "训练进步统计不能代替任务完成记录；自由文本限制需用户复核，服务端只自动检查日期、分钟预算、训练频次。"}
            elif call.name == "propose_weekly_plan":
                args = WeeklyPlanArguments.model_validate(call.arguments)
                if self._profile is None:
                    raise ToolArgumentsError("请先读取并补充显式用户档案")
                if self._profile["daily_minutes"] is None or self._profile["training_days_per_week"] is None:
                    raise ToolArgumentsError("生成计划需要每日分钟预算和每周训练频次，请先补充档案")
                request = WeeklyPlanCreate(**args.model_dump(), expected_profile_revision=self._profile["revision"],
                    base_plan_version=self._profile["plan_version"], idempotency_key=self._key(call.name))
                output = self._plans.create(owner_id, request)
                self._approval.wait(owner_id, output["id"])
                output = WeeklyPlanRead.model_validate(output).model_dump(mode="json")
            elif call.name == "propose_plan_adjustment":
                args = AdjustmentArguments.model_validate(call.arguments)
                output, _ = self._plans.adjust(owner_id, args.source_plan_id, self._key(call.name))
                self._approval.wait(owner_id, output["id"])
                output = WeeklyPlanRead.model_validate(output).model_dump(mode="json")
            else:
                raise ToolArgumentsError("不支持的计划工具")
        except ValidationError as exc:
            raise ToolArgumentsError("计划工具参数不合法") from exc
        return ToolExecutionResult(call.call_id, call.name, output)

    def _key(self, tool_name):
        # The model cannot choose identity, expected versions or the retry key.
        return "agent-plan:" + hashlib.sha256(f"{self._request_key}:{tool_name}".encode()).hexdigest()
