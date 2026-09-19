from model_client import (
    FakeModelClient,
    ModelMessage,
    ModelTimeoutError,
    TextResponse,
    ToolCall,
)


def main() -> None:
    query = [ModelMessage(role="user", content="我有哪些任务？")]
    text_client = FakeModelClient(TextResponse(text="我可以帮你查询任务。"))
    print("1. 输入消息:", query)
    print("   普通文本响应:", text_client.complete(query, timeout_seconds=2))

    create_request = [ModelMessage(role="user", content="帮我创建复习 SQL 的任务")]
    tool_client = FakeModelClient(
        ToolCall(
            name="create_task",
            arguments={"title": "复习 SQL", "user_id": 999},
        )
    )
    print("2. 输入消息:", create_request)
    print("   模型提出的工具调用:", tool_client.complete(create_request, timeout_seconds=2))
    print("   当前只展示建议，没有执行工具或写数据库。")

    slow_client = FakeModelClient(
        TextResponse(text="不会返回"),
        required_latency_seconds=3,
    )
    try:
        slow_client.complete(query, timeout_seconds=1)
    except ModelTimeoutError as exc:
        print("3. 超时:", exc)


if __name__ == "__main__":
    main()
