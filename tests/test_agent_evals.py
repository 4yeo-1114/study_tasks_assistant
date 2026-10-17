from agent.agent_evals import AgentEvalCase, run_agent_evals
from agent.agent_loop import AgentAnswer, AgentStepLimitError


def test_eval_suite_scores_behavior_without_exact_answer_matching():
    cases = [
        AgentEvalCase(
            name="readonly-success",
            run=lambda: AgentAnswer("查询完成，目前有一条任务", 2, 1),
            expected_model_steps=2,
            expected_tool_calls=1,
            answer_must_contain=("一条",),
        ),
        AgentEvalCase(
            name="step-limit",
            run=lambda: (_ for _ in ()).throw(AgentStepLimitError("达到上限")),
            expected_error=AgentStepLimitError,
        ),
    ]

    report = run_agent_evals(cases)

    assert report.passed == 2
    assert report.failed == 0
    assert [result.name for result in report.results] == [
        "readonly-success",
        "step-limit",
    ]


def test_eval_suite_reports_behavior_mismatch():
    report = run_agent_evals([
        AgentEvalCase(
            name="unexpected-extra-tool",
            run=lambda: AgentAnswer("完成", 3, 2),
            expected_model_steps=2,
            expected_tool_calls=1,
        )
    ])

    assert report.passed == 0
    assert report.failed == 1
    assert "model_steps expected=2 actual=3" in report.results[0].details
    assert "tool_calls expected=1 actual=2" in report.results[0].details
