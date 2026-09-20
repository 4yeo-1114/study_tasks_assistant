import json
from dataclasses import dataclass
from typing import Sequence

import httpx

from deepseek_api import (
    DeepSeekAPIError,
    DeepSeekNetworkError,
    DeepSeekResponseError,
    DeepSeekSettings,
    DeepSeekTimeoutError,
    DeepSeekUsage,
)
from model_client import ModelMessage


LIST_TASKS_TOOL: dict[str, object] = {
    "type": "function",
    "function": {
        "name": "list_tasks",
        "description": "查询当前用户的学习任务；只提出查询，不修改任务。",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "completed"],
                    "description": "可选的任务状态筛选条件",
                },
                "priority": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                    "description": "可选的优先级筛选条件",
                },
            },
            "additionalProperties": False,
        },
    },
}


class DeepSeekToolResponseError(DeepSeekResponseError):
    pass


@dataclass(frozen=True)
class ToolCallProposal:
    call_id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class ToolProposal:
    finish_reason: str
    model: str
    calls: tuple[ToolCallProposal, ...]
    usage: DeepSeekUsage


def request_tool_proposal(
    messages: Sequence[ModelMessage],
    *,
    tools: Sequence[dict[str, object]],
    settings: DeepSeekSettings,
    timeout_seconds: float = 30.0,
    transport: httpx.BaseTransport | None = None,
) -> ToolProposal:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds 必须大于 0")

    allowed_names = _tool_names(tools)
    payload = {
        "model": settings.model,
        "messages": [
            {"role": message.role, "content": message.content}
            for message in messages
        ],
        "tools": list(tools),
        "tool_choice": "required",
        "thinking": {"type": "disabled"},
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
        raise DeepSeekTimeoutError("DeepSeek 工具提案请求超时") from exc
    except httpx.RequestError as exc:
        raise DeepSeekNetworkError("无法连接 DeepSeek 获取工具提案") from exc

    if not response.is_success:
        message = _safe_error_message(response, api_key=settings.api_key)
        raise DeepSeekAPIError(response.status_code, message)

    data = _response_object(response)
    try:
        choice = data["choices"][0]
        finish_reason = choice["finish_reason"]
        tool_calls = choice["message"]["tool_calls"]
        model = data["model"]
        usage = data["usage"]
        prompt_tokens = usage["prompt_tokens"]
        completion_tokens = usage["completion_tokens"]
        total_tokens = usage["total_tokens"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DeepSeekToolResponseError(
            "DeepSeek 工具提案响应结构不完整"
        ) from exc

    if finish_reason != "tool_calls" or not isinstance(tool_calls, list) or not tool_calls:
        raise DeepSeekToolResponseError("DeepSeek 没有返回工具提案")
    if not isinstance(model, str) or not all(
        isinstance(value, int)
        for value in (prompt_tokens, completion_tokens, total_tokens)
    ):
        raise DeepSeekToolResponseError("DeepSeek 工具提案响应结构不完整")

    calls = tuple(
        _parse_tool_call(raw_call, allowed_names=allowed_names)
        for raw_call in tool_calls
    )
    return ToolProposal(
        finish_reason=finish_reason,
        model=model,
        calls=calls,
        usage=DeepSeekUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        ),
    )


def _tool_names(tools: Sequence[dict[str, object]]) -> set[str]:
    names: set[str] = set()
    for tool in tools:
        function = tool.get("function")
        if tool.get("type") != "function" or not isinstance(function, dict):
            raise ValueError("tools 中存在不合法的函数定义")
        name = function.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("tools 中存在不合法的函数名")
        names.add(name)
    if not names:
        raise ValueError("tools 不能为空")
    return names


def _parse_tool_call(
    raw_call: object,
    *,
    allowed_names: set[str],
) -> ToolCallProposal:
    if not isinstance(raw_call, dict):
        raise DeepSeekToolResponseError("DeepSeek 工具提案响应结构不完整")
    function = raw_call.get("function")
    if not isinstance(function, dict):
        raise DeepSeekToolResponseError("DeepSeek 工具提案响应结构不完整")

    call_id = raw_call.get("id")
    call_type = raw_call.get("type")
    name = function.get("name")
    raw_arguments = function.get("arguments")
    if (
        not isinstance(call_id, str)
        or not call_id
        or call_type != "function"
        or not isinstance(name, str)
        or not isinstance(raw_arguments, str)
    ):
        raise DeepSeekToolResponseError("DeepSeek 工具提案响应结构不完整")
    if name not in allowed_names:
        raise DeepSeekToolResponseError(f"DeepSeek 提出了未知工具: {name}")

    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise DeepSeekToolResponseError(
            f"工具 {name} 的 arguments 不是合法 JSON"
        ) from exc
    if not isinstance(arguments, dict):
        raise DeepSeekToolResponseError(
            f"工具 {name} 的 arguments 必须是 JSON 对象"
        )

    return ToolCallProposal(
        call_id=call_id,
        name=name,
        arguments=arguments,
    )


def _response_object(response: httpx.Response) -> dict[str, object]:
    try:
        data = response.json()
    except ValueError as exc:
        raise DeepSeekToolResponseError(
            "DeepSeek 工具提案响应不是合法 JSON"
        ) from exc
    if not isinstance(data, dict):
        raise DeepSeekToolResponseError("DeepSeek 工具提案响应结构不完整")
    return data


def _safe_error_message(response: httpx.Response, *, api_key: str) -> str:
    try:
        data = response.json()
    except ValueError:
        return "错误响应不是合法 JSON"
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message:
                return message.replace(api_key, "[REDACTED]")
    return "未提供错误详情"
