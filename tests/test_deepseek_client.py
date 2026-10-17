import logging

import httpx
import pytest

from llm.deepseek_api import DeepSeekAPIError, DeepSeekSettings
from llm.deepseek_client import DeepSeekClient
from llm.model_client import ModelMessage


SETTINGS = DeepSeekSettings(
    api_key="secret-client-key",
    base_url="https://api.deepseek.example",
    model="test-model",
)
MESSAGES = [ModelMessage(role="user", content="private prompt text")]


def test_client_chat_reuses_configuration() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret-client-key"
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
        )

    client = DeepSeekClient(
        settings=SETTINGS,
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    assert client.chat(MESSAGES).text == "ok"


def test_client_stream_reuses_configuration() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=(
                b'data: {"choices":[{"delta":{"content":"O"}}]}\n\n'
                b'data: {"choices":[{"delta":{"content":"K"}}]}\n\n'
                b"data: [DONE]\n\n"
            ),
        )
    )
    client = DeepSeekClient(settings=SETTINGS, transport=transport)

    assert "".join(client.stream(MESSAGES)) == "OK"


def test_client_logs_metadata_without_secrets_or_prompt(caplog) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "model": "test-model",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
        )
    )
    client = DeepSeekClient(settings=SETTINGS, transport=transport)

    with caplog.at_level(logging.INFO, logger="study_task.deepseek"):
        client.chat(MESSAGES)

    assert "mode=chat" in caplog.text
    assert "status=succeeded" in caplog.text
    assert "request_id=" in caplog.text
    assert "message_count=1" in caplog.text
    assert SETTINGS.api_key not in caplog.text
    assert MESSAGES[0].content not in caplog.text


def test_client_logs_failure_type_and_preserves_exception(caplog) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            503,
            json={"error": {"message": "temporarily unavailable"}},
        )
    )
    client = DeepSeekClient(settings=SETTINGS, transport=transport)

    with caplog.at_level(logging.WARNING, logger="study_task.deepseek"):
        with pytest.raises(DeepSeekAPIError):
            client.chat(MESSAGES)

    assert "status=failed" in caplog.text
    assert "error_type=DeepSeekAPIError" in caplog.text
    assert SETTINGS.api_key not in caplog.text
    assert MESSAGES[0].content not in caplog.text
