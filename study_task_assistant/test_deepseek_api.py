import json

import httpx
import pytest

from deepseek_api import (
    DeepSeekAPIError,
    DeepSeekConfigurationError,
    DeepSeekReply,
    DeepSeekResponseError,
    DeepSeekSettings,
    DeepSeekUsage,
    request_chat,
)
from model_client import ModelMessage


def test_settings_require_a_non_blank_api_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)

    with pytest.raises(
        DeepSeekConfigurationError,
        match="缺少环境变量 DEEPSEEK_API_KEY",
    ):
        DeepSeekSettings.from_env()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "   ")
    with pytest.raises(DeepSeekConfigurationError):
        DeepSeekSettings.from_env()


def test_settings_load_key_and_normalize_base_url(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://example.test/")
    monkeypatch.setenv("DEEPSEEK_MODEL", "test-model")

    assert DeepSeekSettings.from_env() == DeepSeekSettings(
        api_key="test-key",
        base_url="https://example.test",
        model="test-model",
    )


def test_request_chat_sends_contract_and_parses_reply():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-key"
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content) == {
            "model": "test-model",
            "messages": [{"role": "user", "content": "用一句话解释 API"}],
            "stream": False,
        }
        return httpx.Response(
            200,
            json={
                "id": "response-1",
                "object": "chat.completion",
                "created": 1_800_000_000,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "API 是程序之间约定的通信接口。",
                        },
                        "finish_reason": "stop",
                        "logprobs": None,
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 8,
                    "total_tokens": 18,
                },
            },
        )

    reply = request_chat(
        [ModelMessage(role="user", content="用一句话解释 API")],
        settings=DeepSeekSettings(
            api_key="test-key",
            base_url="https://api.deepseek.com",
            model="test-model",
        ),
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )

    assert reply == DeepSeekReply(
        text="API 是程序之间约定的通信接口。",
        model="test-model",
        usage=DeepSeekUsage(
            prompt_tokens=10,
            completion_tokens=8,
            total_tokens=18,
        ),
    )


def test_request_chat_turns_http_error_into_safe_api_error():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "error": {
                    "message": "Authentication Fails",
                    "type": "authentication_error",
                }
            },
        )

    with pytest.raises(DeepSeekAPIError) as caught:
        request_chat(
            [ModelMessage(role="user", content="hello")],
            settings=DeepSeekSettings(
                api_key="test-key",
                base_url="https://api.deepseek.com",
                model="test-model",
            ),
            transport=httpx.MockTransport(handler),
        )

    assert caught.value.status_code == 401
    assert "Authentication Fails" in str(caught.value)
    assert "test-key" not in str(caught.value)


def test_request_chat_rejects_malformed_success_response():
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "model": "test-model",
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
        )
    )

    with pytest.raises(DeepSeekResponseError, match="响应结构不完整"):
        request_chat(
            [ModelMessage(role="user", content="hello")],
            settings=DeepSeekSettings(
                api_key="test-key",
                base_url="https://api.deepseek.com",
                model="test-model",
            ),
            transport=transport,
        )


def test_request_chat_requires_a_positive_timeout():
    with pytest.raises(ValueError, match="timeout_seconds 必须大于 0"):
        request_chat(
            [ModelMessage(role="user", content="hello")],
            settings=DeepSeekSettings(
                api_key="test-key",
                base_url="https://api.deepseek.com",
                model="test-model",
            ),
            timeout_seconds=0,
        )
