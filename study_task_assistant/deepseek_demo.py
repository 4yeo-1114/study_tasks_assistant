import sys
from collections.abc import Sequence

from deepseek_api import (
    DeepSeekAPIError,
    DeepSeekConfigurationError,
    DeepSeekNetworkError,
    DeepSeekResponseError,
    DeepSeekSettings,
    request_chat,
)
from model_client import ModelMessage


DEFAULT_PROMPT = "请用一句话解释 HTTP API 是什么"


def prompt_from_args(argv: Sequence[str]) -> str:
    return " ".join(argv).strip() or DEFAULT_PROMPT


def main(argv: Sequence[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    prompt = prompt_from_args(arguments)

    try:
        settings = DeepSeekSettings.from_env()
        reply = request_chat(
            [ModelMessage(role="user", content=prompt)],
            settings=settings,
            timeout_seconds=30,
        )
    except (
        DeepSeekConfigurationError,
        DeepSeekAPIError,
        DeepSeekNetworkError,
        DeepSeekResponseError,
    ) as exc:
        print(f"调用失败: {exc}", file=sys.stderr)
        return 1

    print(f"模型: {reply.model}")
    print(f"回答: {reply.text}")
    print(
        "Token 用量: "
        f"输入 {reply.usage.prompt_tokens} / "
        f"输出 {reply.usage.completion_tokens} / "
        f"总计 {reply.usage.total_tokens}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
