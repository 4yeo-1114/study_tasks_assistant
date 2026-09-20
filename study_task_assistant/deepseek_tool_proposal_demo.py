import json
import sys

from deepseek_api import (
    DeepSeekAPIError,
    DeepSeekConfigurationError,
    DeepSeekNetworkError,
    DeepSeekResponseError,
    DeepSeekSettings,
)
from deepseek_tools import LIST_TASKS_TOOL, request_tool_proposal
from model_client import ModelMessage


def main() -> int:
    try:
        proposal = request_tool_proposal(
            [
                ModelMessage(
                    role="user",
                    content="查询所有待完成的高优先级任务",
                )
            ],
            tools=[LIST_TASKS_TOOL],
            settings=DeepSeekSettings.from_env(),
        )
    except (
        DeepSeekConfigurationError,
        DeepSeekAPIError,
        DeepSeekNetworkError,
        DeepSeekResponseError,
    ) as exc:
        print(f"工具提案请求失败: {exc}", file=sys.stderr)
        return 1

    print(f"模型: {proposal.model}")
    print(f"结束原因: {proposal.finish_reason}")
    for call in proposal.calls:
        print(f"Call ID: {call.call_id}")
        print(f"工具名: {call.name}")
        print(
            "参数: "
            + json.dumps(call.arguments, ensure_ascii=False, sort_keys=True)
        )
    print("执行状态: 未执行任何工具，数据库未被本程序修改")
    print(f"Token 总量: {proposal.usage.total_tokens}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
