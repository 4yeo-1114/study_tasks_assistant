import json
import logging
from dataclasses import dataclass

import httpx

from deepseek_api import (
    DeepSeekAPIError,
    DeepSeekNetworkError,
    DeepSeekSettings,
    DeepSeekTimeoutError,
)
from deepseek_tools import (
    DeepSeekToolResponseError,
    _parse_tool_call,
    _safe_error_message,
)
from readonly_tools import READ_ONLY_TOOLS, TaskQueryService, execute_readonly_tool


logger = logging.getLogger("study_task.agent")


class AgentStepLimitError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentAnswer:
    answer: str
    model_steps: int
    tool_calls: int


def run_readonly_agent(
    question: str,
    *,
    user_id: int,
    service: TaskQueryService,
    settings: DeepSeekSettings,
    max_model_steps: int = 3,
    timeout_seconds: float = 30.0,
    transport: httpx.BaseTransport | None = None,
) -> AgentAnswer:
    """Run only the two approved read tools; never infer identity from model data."""
    if not question.strip():
        raise ValueError("问题不能为空")
    if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id < 1:
        raise ValueError("可信 user_id 必须是正整数")
    if max_model_steps < 1:
        raise ValueError("max_model_steps 必须大于 0")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds 必须大于 0")

    messages: list[dict[str, object]] = [{"role": "user", "content": question}]
    call_count = 0
    seen_call_ids: set[str] = set()
    allowed_names = {"list_tasks", "get_task"}

    try:
        with httpx.Client(timeout=timeout_seconds, transport=transport) as client:
            for step in range(1, max_model_steps + 1):
                response = client.post(
                    f"{settings.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.api_key}"},
                    json={
                        "model": settings.model,
                        "messages": messages,
                        "tools": READ_ONLY_TOOLS,
                        "tool_choice": "required" if step == 1 else "auto",
                        "thinking": {"type": "disabled"},
                        "stream": False,
                    },
                )
                if not response.is_success:
                    raise DeepSeekAPIError(
                        response.status_code,
                        _safe_error_message(response, api_key=settings.api_key),
                    )

                try:
                    data = response.json()
                    choice = data["choices"][0]
                    reason = choice["finish_reason"]
                    message = choice["message"]
                    if message["role"] != "assistant":
                        raise ValueError("unexpected role")
                except (ValueError, KeyError, IndexError, TypeError) as exc:
                    raise DeepSeekToolResponseError("Agent 模型响应结构不完整") from exc

                logger.info("agent_step step=%s finish_reason=%s", step, reason)

                if reason == "stop":
                    content = message.get("content")
                    if not isinstance(content, str) or not content.strip():
                        raise DeepSeekToolResponseError("Agent 最终回答为空")
                    return AgentAnswer(content, step, call_count)

                if reason != "tool_calls":
                    raise DeepSeekToolResponseError("Agent 响应未完整结束")
                raw_calls = message.get("tool_calls")
                if not isinstance(raw_calls, list) or not raw_calls:
                    raise DeepSeekToolResponseError("Agent 工具提案结构不完整")
                if step == max_model_steps:
                    raise AgentStepLimitError("Agent 达到模型步数上限，未得到最终回答")

                calls = tuple(
                    _parse_tool_call(raw, allowed_names=allowed_names)
                    for raw in raw_calls
                )
                if len({call.call_id for call in calls}) != len(calls):
                    raise DeepSeekToolResponseError("Agent 工具 Call ID 重复")
                if any(call.call_id in seen_call_ids for call in calls):
                    raise DeepSeekToolResponseError("Agent 工具 Call ID 重复")
                seen_call_ids.update(call.call_id for call in calls)

                # Preserve the exact assistant call before sending matching tool results.
                messages.append({
                    "role": "assistant",
                    "content": message.get("content"),
                    "tool_calls": raw_calls,
                })
                for call in calls:
                    logger.info(
                        "agent_tool step=%s name=%s call_id=%s",
                        step, call.name, call.call_id,
                    )
                    result = execute_readonly_tool(
                        call, user_id=user_id, service=service
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": result.call_id,
                        "content": json.dumps(result.output, ensure_ascii=False),
                    })
                    call_count += 1
    except httpx.TimeoutException as exc:
        raise DeepSeekTimeoutError("Agent 模型请求超时") from exc
    except httpx.RequestError as exc:
        raise DeepSeekNetworkError("Agent 无法连接 DeepSeek") from exc

    raise AgentStepLimitError("Agent 达到模型步数上限")
