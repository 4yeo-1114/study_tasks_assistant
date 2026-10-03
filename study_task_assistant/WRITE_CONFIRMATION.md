# W7-04：创建任务的提案与确认

模型在这一步只能**建议**调用 `create_task`。应用先检查工具名和参数，把标题、优先级、截止日期存为绑定当前用户的 `pending` 提案；此时 `tasks` 表不变。提案有效期为 15 分钟。只有持有该用户有效 JWT 的确认请求，或本地演示中登录后的明确 `yes`，才能创建任务。

## 数据流

```text
用户描述 → DeepSeek 返回 create_task(arguments)
         → Pydantic 拒绝空标题、非法优先级、模型提供的 user_id/owner_id
         → task_proposals 新增 pending 记录（随机提案 ID）
         → 向用户展示待创建内容
         → 用户确认 → 同一事务中将提案改为 confirmed 并插入 tasks
                     → 重复确认只读取原 task_id，不再插入
         → 用户拒绝 → 状态变为 rejected，之后不能确认
```

用户身份由登录后的服务端代码提供，不从模型的 `arguments` 中取。模型的 `call_id` 用于关联模型消息；应用生成的提案 ID 用于后续确认与幂等，两者职责不同。别人即使猜到提案 ID，也不能读取、确认或拒绝它。过期提案不能确认。若已确认的任务后来被删除，重复确认仍不会重新创建。

## 实际运行

本机默认 `tasks.db` 已升级到 `0004_proposal_task_history`；其他数据库先在项目目录执行 `python -m alembic upgrade head`。若使用 PostgreSQL，确保迁移命令和演示程序读取相同的 `DATABASE_URL`。环境变量 `DEEPSEEK_API_KEY` 仍需在当前终端有效，密钥不要写进源码。

```powershell
cd D:\dev-learning\study_task_assistant
python task_proposal_demo.py
```

用已有任务助手账号登录，输入类似“明天复习 SQL，设为高优先级”。程序会打印确认前任务数、模型提出的标题/优先级/日期/提案 ID，以及结束后任务数。输入 `yes` 才创建任务；输入其他内容会拒绝。建议先试一次拒绝（任务数不变），再试一次确认（任务数增加 1）。演示只在用户确认后写任务；运行前不需要自己写测试函数。

API 也提供以下 JWT 保护的路由，可在 `/docs` 中查看：

| 路由 | 作用 |
| --- | --- |
| `POST /agent/task-proposals` | 将自然语言交给模型，返回待确认提案；不写 `tasks` |
| `GET /agent/task-proposals/{id}` | 仅所属用户查看提案 |
| `POST /agent/task-proposals/{id}/confirm` | 确认；重复调用返回同一任务，不重复创建 |
| `POST /agent/task-proposals/{id}/reject` | 拒绝待确认提案 |

未登录返回 401；其他用户的提案返回 404；已拒绝的提案确认返回 409；过期确认返回 410。网络重试或用户重复点击确认，都不会凭同一提案创建第二条任务。

本单元需要你重点解释：为什么 `finish_reason=tool_calls` 仍不能写库；为什么应用提案 ID 和模型 call ID 不能混用；确认时如何同时保证用户归属、未过期和只执行一次。自动化测试与迁移测试由 AI 负责。
