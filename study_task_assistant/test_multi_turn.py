import json

import httpx
import pytest

from deepseek_api import DeepSeekSettings
from deepseek_multi_turn_demo import run_two_turn_chat, trim_messages
from model_client import ModelMessage


def test_second_request_resends_first_question_and_answer():
    payloads: list[dict[str, object]] = []
    responses = [
        ("列表是有序的可变序列。", 12, 8, 20),
        ("列表可变，元组不可变。", 30, 9, 39),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        text, prompt_tokens, completion_tokens, total_tokens = responses[
            len(payloads) - 1
        ]
        return httpx.Response(
            200,
            json={
                "id": f"response-{len(payloads)}",
                "object": "chat.completion",
                "created": 1_800_000_000,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": "stop",
                        "logprobs": None,
                    }
                ],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                },
            },
        )

    result = run_two_turn_chat(
        settings=DeepSeekSettings(
            api_key="test-key",
            base_url="https://api.deepseek.com",
            model="test-model",
        ),
        first_question="Python 中的列表是什么？",
        second_question="它和元组最大的区别是什么？",
        transport=httpx.MockTransport(handler),
    )

    assert payloads[0]["messages"] == [
        {"role": "user", "content": "Python 中的列表是什么？"},
    ]
    assert payloads[1]["messages"] == [
        {"role": "user", "content": "Python 中的列表是什么？"},
        {"role": "assistant", "content": "列表是有序的可变序列。"},
        {"role": "user", "content": "它和元组最大的区别是什么？"},
    ]
    assert result.messages == (
        ModelMessage(role="user", content="Python 中的列表是什么？"),
        ModelMessage(role="assistant", content="列表是有序的可变序列。"),
        ModelMessage(role="user", content="它和元组最大的区别是什么？"),
        ModelMessage(role="assistant", content="列表可变，元组不可变。"),
    )
    assert result.first_reply.usage.prompt_tokens == 12
    assert result.second_reply.usage.prompt_tokens == 30


def test_trim_messages_keeps_system_and_last_two_regular_messages():
    messages = [
        ModelMessage(role="system", content="你是学习助手"),
        ModelMessage(role="user", content="问题一"),
        ModelMessage(role="assistant", content="回答一"),
        ModelMessage(role="user", content="问题二"),
        ModelMessage(role="assistant", content="回答二"),
    ]

    assert trim_messages(messages, max_non_system_messages=2) == [
        ModelMessage(role="system", content="你是学习助手"),
        ModelMessage(role="user", content="问题二"),
        ModelMessage(role="assistant", content="回答二"),
    ]
    assert len(messages) == 5


def test_trim_messages_without_system_keeps_last_two_messages():
    messages = [
        ModelMessage(role="user", content="问题一"),
        ModelMessage(role="assistant", content="回答一"),
        ModelMessage(role="user", content="问题二"),
    ]

    assert trim_messages(messages, max_non_system_messages=2) == [
        ModelMessage(role="assistant", content="回答一"),
        ModelMessage(role="user", content="问题二"),
    ]


def test_trim_messages_rejects_non_positive_limit():
    with pytest.raises(ValueError, match="必须大于 0"):
        trim_messages([], max_non_system_messages=0)
