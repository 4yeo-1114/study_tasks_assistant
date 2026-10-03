import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Sequence

import httpx

from model_client import ModelMessage


class DeepSeekConfigurationError(ValueError):
    pass


class DeepSeekAPIError(RuntimeError):
    def __init__(self, status_code: int, provider_message: str) -> None:
        self.status_code = status_code
        self.retryable = status_code == 429 or 500 <= status_code <= 599
        super().__init__(f"DeepSeek API 返回 HTTP {status_code}: {provider_message}")


class DeepSeekNetworkError(RuntimeError):
    pass


class DeepSeekTimeoutError(DeepSeekNetworkError):
    pass


class DeepSeekResponseError(RuntimeError):
    pass


@dataclass(frozen=True)
class DeepSeekSettings:
    api_key: str
    base_url: str
    model: str

    @classmethod
    def from_env(cls) -> "DeepSeekSettings":
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            raise DeepSeekConfigurationError("缺少环境变量 DEEPSEEK_API_KEY")

        base_url = (
            os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
            or "https://api.deepseek.com"
        )
        model = (
            os.getenv("DEEPSEEK_MODEL", "deepseek-flash").strip()
            or "deepseek-flash"
        )
        return cls(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            model=model,
        )


@dataclass(frozen=True)
class DeepSeekUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class DeepSeekReply:
    text: str
    model: str
    usage: DeepSeekUsage


def request_chat(
    messages: Sequence[ModelMessage],
    *,
    settings: DeepSeekSettings,
    timeout_seconds: float = 30.0,
    transport: httpx.BaseTransport | None = None,
) -> DeepSeekReply:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds 必须大于 0")

    payload = {
        "model": settings.model,
        "messages": [
            {"role": message.role, "content": message.content}
            for message in messages
        ],
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {settings.api_key}"}

    try:
        with httpx.Client(timeout=timeout_seconds, transport=transport) as client:
            response = client.post(
                f"{settings.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
    except httpx.TimeoutException as exc:
        raise DeepSeekTimeoutError("DeepSeek 请求超时") from exc
    except httpx.RequestError as exc:
        raise DeepSeekNetworkError("无法连接 DeepSeek") from exc

    # 非 2xx：先尝试读取服务端的 JSON 错误信息。
    if not response.is_success:
        _raise_api_error(response, api_key=settings.api_key)

    # 2xx：成功响应必须符合 DeepSeek 的 JSON 响应结构。
    data = _response_json(response)
    try:
        text = data["choices"][0]["message"]["content"]
        model = data["model"]
        usage = data["usage"]
        prompt_tokens = usage["prompt_tokens"]
        completion_tokens = usage["completion_tokens"]
        total_tokens = usage["total_tokens"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DeepSeekResponseError("DeepSeek 响应结构不完整") from exc

    if not isinstance(text, str) or not isinstance(model, str):
        raise DeepSeekResponseError("DeepSeek 响应结构不完整")
    if not all(
        isinstance(value, int)
        for value in (prompt_tokens, completion_tokens, total_tokens)
    ):
        raise DeepSeekResponseError("DeepSeek 响应结构不完整")

    return DeepSeekReply(
        text=text,
        model=model,
        usage=DeepSeekUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
    )


def stream_chat(
    messages: Sequence[ModelMessage],
    *,
    settings: DeepSeekSettings,
    timeout_seconds: float = 30.0,
    transport: httpx.BaseTransport | None = None,
) -> Iterator[str]:
    """Yield user-visible text chunks from DeepSeek's SSE response."""
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds 必须大于 0")

    payload = {
        "model": settings.model,
        "messages": [
            {"role": message.role, "content": message.content}
            for message in messages
        ],
        "stream": True,
    }
    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Accept": "text/event-stream",
    }

    try:
        with httpx.Client(timeout=timeout_seconds, transport=transport) as client:
            with client.stream(
                "POST",
                f"{settings.base_url}/chat/completions",
                headers=headers,
                json=payload,
            ) as response:
                if not response.is_success:
                    response.read()
                    _raise_api_error(response, api_key=settings.api_key)

                for line in response.iter_lines():
                    if not line or line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        raise DeepSeekResponseError("DeepSeek SSE 事件格式不合法")

                    event_text = line.removeprefix("data:").strip()
                    if event_text == "[DONE]":
                        return

                    try:
                        event = json.loads(event_text)
                    except json.JSONDecodeError as exc:
                        raise DeepSeekResponseError(
                            "DeepSeek SSE 事件不是合法 JSON"
                        ) from exc

                    try:
                        delta = event["choices"][0]["delta"]
                    except (KeyError, IndexError, TypeError) as exc:
                        raise DeepSeekResponseError(
                            "DeepSeek SSE 响应结构不完整"
                        ) from exc

                    if not isinstance(delta, dict):
                        raise DeepSeekResponseError(
                            "DeepSeek SSE 响应结构不完整"
                        )
                    content = delta.get("content")
                    if content is None or content == "":
                        continue
                    if not isinstance(content, str):
                        raise DeepSeekResponseError(
                            "DeepSeek SSE 响应结构不完整"
                        )
                    yield content

                raise DeepSeekResponseError(
                    "DeepSeek 流在 [DONE] 前结束，已接收内容不完整"
                )
    except httpx.TimeoutException as exc:
        raise DeepSeekTimeoutError("DeepSeek 流式响应超时") from exc
    except httpx.RequestError as exc:
        raise DeepSeekNetworkError("DeepSeek 流式连接中断") from exc


def _response_json(response: httpx.Response) -> dict[str, object]:
    try:
        data = response.json()
    except ValueError as exc:
        raise DeepSeekResponseError("DeepSeek 返回的不是合法 JSON") from exc
    if not isinstance(data, dict):
        raise DeepSeekResponseError("DeepSeek 响应结构不完整")
    return data


def _provider_error_message(data: dict[str, object]) -> str:
    error = data.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message:
            return message
    return "未提供错误详情"

#把错误响应包装为报错信息
def _raise_api_error(response: httpx.Response, *, api_key: str) -> None:
    try:
        data = _response_json(response)
        message = _provider_error_message(data).replace(api_key, "[REDACTED]")
    except DeepSeekResponseError:
        message = "错误响应不是合法 JSON"
    raise DeepSeekAPIError(response.status_code, message)
