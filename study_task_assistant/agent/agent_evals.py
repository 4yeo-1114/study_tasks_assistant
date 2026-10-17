from collections.abc import Callable
from dataclasses import dataclass

from agent.agent_loop import AgentAnswer


@dataclass(frozen=True)
class AgentEvalCase:
    """A repeatable behavior contract for one Agent scenario."""

    name: str
    run: Callable[[], AgentAnswer]
    expected_model_steps: int | None = None
    expected_tool_calls: int | None = None
    answer_must_contain: tuple[str, ...] = ()
    expected_error: type[Exception] | None = None


@dataclass(frozen=True)
class AgentEvalResult:
    name: str
    passed: bool
    details: str


@dataclass(frozen=True)
class AgentEvalReport:
    results: tuple[AgentEvalResult, ...]

    @property
    def passed(self) -> int:
        return sum(result.passed for result in self.results)

    @property
    def failed(self) -> int:
        return len(self.results) - self.passed


def run_agent_evals(cases: list[AgentEvalCase]) -> AgentEvalReport:
    """Run the same scenarios and score observable behavior."""
    results = tuple(_run_case(case) for case in cases)
    return AgentEvalReport(results)


def _run_case(case: AgentEvalCase) -> AgentEvalResult:
    try:
        answer = case.run()
    except Exception as exc:
        #如果发生了case预期的错误就返回pass=true的评估结果
        if case.expected_error is not None and isinstance(exc, case.expected_error):
            return AgentEvalResult(case.name, True, type(exc).__name__)
        return AgentEvalResult(
            case.name,
            False,
            f"unexpected error={type(exc).__name__}",
        )
    #分支二这个case可以run
    #保存answer中和case不匹配的位置
    mismatches: list[str] = []
    if case.expected_error is not None:
        mismatches.append(f"expected error={case.expected_error.__name__}")
    if (
        case.expected_model_steps is not None
        and answer.model_steps != case.expected_model_steps
    ):
        mismatches.append(
            "model_steps "
            f"expected={case.expected_model_steps} actual={answer.model_steps}"
        )
    if (
        case.expected_tool_calls is not None
        and answer.tool_calls != case.expected_tool_calls
    ):
        mismatches.append(
            "tool_calls "
            f"expected={case.expected_tool_calls} actual={answer.tool_calls}"
        )
    for text in case.answer_must_contain:
        if text not in answer.answer:
            mismatches.append(f"answer missing={text!r}")

    return AgentEvalResult(
        case.name,
        not mismatches,
        "; ".join(mismatches) if mismatches else "passed",
    )
