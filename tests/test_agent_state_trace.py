import json

import httpx

from agent_loop import AgentState, run_readonly_agent
from deepseek_api import DeepSeekSettings


SETTINGS = DeepSeekSettings("test-key", "https://api.deepseek.example", "deepseek-flash")


def test_agent_answer_contains_explicit_state_trace():
    responses = iter([
        {"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": "直接回答",
        }}]},
    ])

    result = run_readonly_agent(
        "问题",
        user_id=1,
        service=object(),
        settings=SETTINGS,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=next(responses))
        ),
    )

    assert [event.state for event in result.trace] == [
        AgentState.RECEIVED,
        AgentState.DECIDING,
        AgentState.ANSWERING,
        AgentState.COMPLETED,
    ]
    assert result.trace[-1].event == "answer_completed"
