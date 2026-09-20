import sys

from deepseek_api import (
    DeepSeekAPIError,
    DeepSeekConfigurationError,
    DeepSeekNetworkError,
    DeepSeekResponseError,
    DeepSeekSettings,
    stream_chat,
)
from model_client import ModelMessage


def main() -> int:
    received_content = False
    try:
        for chunk in stream_chat(
            [
                ModelMessage(
                    role="user",
                    content="只用一句话解释流式 HTTP 响应。",
                )
            ],
            settings=DeepSeekSettings.from_env(),
        ):
            print(chunk, end="", flush=True)
            received_content = True
    except (
        DeepSeekConfigurationError,
        DeepSeekAPIError,
        DeepSeekNetworkError,
        DeepSeekResponseError,
    ) as exc:
        if received_content:
            print()
        print(f"流式调用失败，已打印内容可能不完整: {exc}", file=sys.stderr)
        return 1

    print()
    print("流式响应完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
