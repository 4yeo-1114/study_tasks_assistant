import sys
from dataclasses import dataclass

import httpx

from deepseek_api import (
    DeepSeekAPIError,
    DeepSeekConfigurationError,
    DeepSeekNetworkError,
    DeepSeekReply,
    DeepSeekResponseError,
    DeepSeekSettings,
    request_chat,
)
from model_client import ModelMessage


@dataclass(frozen=True)
class TwoTurnResult:
    first_reply: DeepSeekReply
    second_reply: DeepSeekReply
    messages: tuple[ModelMessage, ...]


def run_two_turn_chat(
    *,
    settings: DeepSeekSettings,
    first_question: str,
    second_question: str,
    timeout_seconds: float = 30,
    transport: httpx.BaseTransport | None = None,
) -> TwoTurnResult:
    messages = [ModelMessage(role="user", content=first_question)]
    first_reply = request_chat(
        messages,
        settings=settings,
        timeout_seconds=timeout_seconds,
        transport=transport,
    )

    messages.extend(
        [
            ModelMessage(role="assistant", content=first_reply.text),
            ModelMessage(role="user", content=second_question),
        ]
    )
    second_reply = request_chat(
        messages,
        settings=settings,
        timeout_seconds=timeout_seconds,
        transport=transport,
    )
    messages.append(ModelMessage(role="assistant", content=second_reply.text))

    return TwoTurnResult(
        first_reply=first_reply,
        second_reply=second_reply,
        messages=tuple(messages),
    )


def _print_reply(round_number: int, reply: DeepSeekReply) -> None:
    print(f"第 {round_number} 轮回答: {reply.text}")
    print(
        f"第 {round_number} 轮 Token: "
        f"输入 {reply.usage.prompt_tokens} / "
        f"输出 {reply.usage.completion_tokens} / "
        f"总计 {reply.usage.total_tokens}"
    )


def main() -> int:
    try:
        result = run_two_turn_chat(
            settings=DeepSeekSettings.from_env(),
            first_question="Python 中的列表是什么？",
            second_question="它和元组最大的区别是什么？",
        )
    except (
        DeepSeekConfigurationError,
        DeepSeekAPIError,
        DeepSeekNetworkError,
        DeepSeekResponseError,
    ) as exc:
        print(f"调用失败: {exc}", file=sys.stderr)
        return 1

    _print_reply(1, result.first_reply)
    _print_reply(2, result.second_reply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
