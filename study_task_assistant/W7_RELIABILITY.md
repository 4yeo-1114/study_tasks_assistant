# W7-05：Agent 重试、安全日志与固定评测

## 1. 这部分解决什么问题

一次 Agent 运行包含不同性质的动作：模型 HTTP 请求、本地工具执行、数据库读取和数据库写入。它们不能使用同一种重试策略。

- 模型请求尚未返回 Tool Call 时，临时网络错误可以有限重试。
- 已执行的工具不能因为下一次模型请求失败而被重新执行。
- 没有幂等保护的写操作发生超时后，服务端是否已经写入是不确定的，不能直接重放。
- 达到预算后必须停止并抛出错误，不能重新启动整个 Agent 循环。

## 2. 模块职责

| 模块 | 职责 | 不负责什么 |
|---|---|---|
| `core/reliability.py` 的 `RetryPolicy` | 根据错误类型、操作类型和 attempt 判断能否重试；计算退避时间 | 不发送 HTTP，不执行工具 |
| `core/reliability.py` 的 `call_with_retry` | 管理 attempt、睡眠、request ID 和安全日志 | 不解析模型响应，不知道 Tool Call |
| `agent/agent_loop.py` | 管理 messages、模型 step、Tool Call、工具结果回传和停止条件 | 不自行决定哪些 HTTP 错误可重试 |
| `llm/deepseek_tools.py` | 请求并解析单轮工具提案 | 不执行模型提出的工具 |
| `agent/agent_evals.py` | 重复运行固定场景，比较可观察行为 | 不修改 Agent，不按完整回答逐字评分 |

## 3. 一次带重试的只读 Agent 数据流

```text
run_readonly_agent
  └─ step 1
      └─ call_with_retry（同一个 request_id）
          ├─ attempt 1 → HTTP 503 → 记录 retrying → 退避
          └─ attempt 2 → HTTP 200 → 记录 succeeded
      └─ 解析 JSON / Tool Call
      └─ 白名单和参数校验
      └─ 本地执行 list_tasks 一次
      └─ 把 assistant tool_calls 与 tool result 加入 messages
  └─ step 2
      └─ call_with_retry
          └─ attempt 1 → HTTP 200
      └─ finish_reason=stop → 返回 AgentAnswer
```

这个例子中有 **2 个模型步骤、3 次真实 HTTP 请求、1 次工具执行**。`attempt` 统计某一个模型步骤内部的 HTTP 尝试；`step` 统计 Agent 与模型交互的轮次，两者不能混用。

## 4. 重试判断表

| 场景 | 是否自动重试 | 原因 |
|---|---|---|
| 401 API Key 错误 | 否 | 凭据不变，重复请求仍会失败 |
| 422 或其他永久请求错误 | 否 | 原请求本身需要修改 |
| 429 | 是，有限次数 | 通常表示限流，稍后可能恢复 |
| 503 | 是，有限次数 | 已收到 HTTP 响应，服务暂时不可用 |
| 连接错误或读超时 | 是，限于安全操作 | 请求可能尚未完成，需要结合副作用判断 |
| HTTP 200 但 JSON/schema 错误 | 不重放原 HTTP 请求 | 这是响应协议或 Agent 纠错问题 |
| 只读工具查询 | 可有限重试 | 重复读取通常不产生副作用 |
| `confirm(user_id, proposal_id)` | 可用同一组 ID 恢复 | 条件更新和 confirmed 分支提供幂等性 |
| 普通 `POST /tasks` 超时 | 否 | 结果未知，重放可能重复创建 |

当前默认策略最多尝试 3 次，退避时间依次从 0.25 秒、0.5 秒开始，并受最大值限制。最后一次失败后不再睡眠，直接抛出原类型化异常。

## 5. 为什么工具不会被重复执行

重试器只包住 `client.post()`。以下动作都在 `call_with_retry()` 成功返回以后：

1. 解析模型 JSON；
2. 检查 `finish_reason`；
3. 校验工具名和 arguments；
4. 调用 `execute_readonly_tool()`；
5. 把工具结果加入消息历史。

因此，HTTP attempt 1 失败时根本没有 Tool Call 可执行。attempt 2 成功后，工具才执行一次。如果把重试器包在整个 `run_readonly_agent()` 外面，已经完成的工具轮次也可能被重放，这才是错误边界。

## 6. 日志为什么安全

重试日志只记录：

- `request_id`：同一个逻辑请求的关联 ID；
- `operation`：操作类别；
- `attempt`：本次是第几次实际尝试；
- `status`：`started`、`retrying`、`succeeded` 或 `failed`；
- `error_type` 与 HTTP 状态码。

日志不记录 API Key、Authorization 请求头、完整 messages、用户问题、模型回答或异常原文。这样仍能追踪故障，又不会把凭据和正文写入日志。

## 7. 固定评测与普通测试的区别

固定评测把场景、输入和预期行为保存在版本库中，每次修改 Agent 后重复运行。当前评测器可以检查：

- 是否应该成功或抛出某一类错误；
- 模型步骤数量；
- 工具调用数量；
- 回答是否包含必要事实。

它不要求模型输出整句完全相同，因为自然语言措辞可能变化。比如“目前有一条任务”和“查询到 1 条任务”都可能正确，但工具调用两次、越过步数上限或吞掉异常属于行为回归。
