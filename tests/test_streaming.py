import json

import httpx
import pytest

from llm.deepseek_api import (
    DeepSeekAPIError,
    DeepSeekResponseError,
    DeepSeekSettings,
    DeepSeekTimeoutError,
    stream_chat,
)
from llm.model_client import ModelMessage


SETTINGS = DeepSeekSettings(
    api_key="test-key",
    base_url="https://api.deepseek.example",
    model="deepseek-chat",
)
MESSAGES = [ModelMessage(role="user", content="用两个字问好")]


def _sse(*events: object) -> bytes:
    lines = []
    for event in events:
        data = event if isinstance(event, str) else json.dumps(event)
        lines.append(f"data: {data}\n\n")
    return "".join(lines).encode()


def test_stream_chat_yields_only_content_until_done() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["stream"] is True
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse(
                {"choices": [{"delta": {"role": "assistant"}}]},
                {"choices": [{"delta": {"reasoning_content": "先思考"}}]},
                {"choices": [{"delta": {"content": "你"}}]},
                {"choices": [{"delta": {"content": "好"}}]},
                {"choices": [{"delta": {"content": ""}, "finish_reason": "stop"}]},
                "[DONE]",
            ),
        )

    chunks = list(
        stream_chat(
            MESSAGES,
            settings=SETTINGS,
            transport=httpx.MockTransport(handler),
        )
    )

    assert chunks == ["你", "好"]


def test_stream_chat_rejects_malformed_json_event() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b"data: {not-json}\n\n",
        )
    )

    with pytest.raises(DeepSeekResponseError, match="事件不是合法 JSON"):
        list(stream_chat(MESSAGES, settings=SETTINGS, transport=transport))


def test_stream_chat_requires_done_marker() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse({"choices": [{"delta": {"content": "半句"}}]}),
        )
    )
    stream = stream_chat(MESSAGES, settings=SETTINGS, transport=transport)

    assert next(stream) == "半句"
    with pytest.raises(DeepSeekResponseError, match=r"\[DONE\] 前结束"):
        next(stream)


def test_stream_chat_maps_http_error_and_redacts_key() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            503,
            json={"error": {"message": "temporary failure for test-key"}},
        )
    )

    with pytest.raises(DeepSeekAPIError) as exc_info:
        list(stream_chat(MESSAGES, settings=SETTINGS, transport=transport))

    assert exc_info.value.status_code == 503
    assert exc_info.value.retryable is True
    assert "test-key" not in str(exc_info.value)


class _TimeoutAfterOneEvent(httpx.SyncByteStream):
    def __iter__(self):
        yield _sse({"choices": [{"delta": {"content": "半句"}}]})
        raise httpx.ReadTimeout("stream stalled")

    def close(self) -> None:
        pass


def test_stream_chat_maps_timeout_during_iteration() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_TimeoutAfterOneEvent(),
        )
    )
    stream = stream_chat(MESSAGES, settings=SETTINGS, transport=transport)

    assert next(stream) == "半句"
    with pytest.raises(DeepSeekTimeoutError, match="流式响应超时"):
        next(stream)
