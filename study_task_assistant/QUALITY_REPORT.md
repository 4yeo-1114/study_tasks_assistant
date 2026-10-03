# 项目质量与失败复盘

## 报告范围

本报告总结 W9-W11 已实现的 Agent、RAG、文档生命周期、任务提案和 Compose 部署能力。它描述的是当前学习项目的验证证据，不是生产 SLA 或大规模容量报告。

## 验证基线

| 项目 | 证据 |
|---|---|
| 自动化回归 | `.venv\\Scripts\\python.exe -m pytest -q`：193 passed, 2 skipped, 1 warning |
| Compose | `db` healthy，`api` running，迁移版本 `0008_task_proposal_idempotency` |
| 静态前端 | `GET /app/` 返回 200 |
| 未认证保护 | `GET /tasks` 返回 401 |
| 文档入库 | 临时资料上传后为 `ready`，生成 1 个 chunk |
| RAG 在线链路 | 2 个模型步骤、知识工具调用、来源引用返回 200 |
| 无证据保护 | 空检索结果时 Agent 明确拒答 |
| 写入确认 | 确认前任务数 0，确认后任务数 1 |
| 幂等 | 同一提案重复确认返回已有 confirmed 结果，没有第二条任务 |

## 失败分层

### 认证层

触发：缺少、过期或签名错误的 JWT。

处理：`api.py` 的 `current_user_id()` 调用 `auth.user_id_for_token()`，失败时返回 401。`user_id` 不从请求 body、前端字段或模型参数读取。

影响：请求在进入任务、文档或 Agent 业务前结束，不会执行用户数据查询。

### 工具协议层

触发：模型返回未知工具名、缺少工具参数、参数超出 schema，或者重复的 `tool_call_id`。

处理：`agent_loop.py` 先进入 `VALIDATING`，再执行白名单和 Pydantic 校验；`api.py` 映射为 422。未知工具不会触发本地函数和数据库操作。

### 模型网络和上游层

触发：连接失败、读取超时、DeepSeek 返回 429/503 或其他非 2xx。

处理：`deepseek_api.py` 将网络异常和 HTTP 错误分类；`reliability.py` 的 `RetryPolicy` 只对模型请求、只读工具和幂等写入允许有限退避重试。401 等认证错误不重试，非幂等写入不放进 HTTP 重试器。

对外结果：上游模型失败通常映射为 502；本地模型配置缺失或 RAG 运行时不可用映射为 503。

### Agent 资源层

触发：模型步骤数、工具调用次数或累计 Token 超过 `AgentBudget`。

处理：`agent_loop.py` 在执行整批工具之前预检查预算。预算不足时整批不执行，避免部分工具产生副作用；API 返回 429。

### 检索层

触发：资料没有命中、召回了错误分块、或候选质量不足。

处理：`retrieval_eval.py` 记录 Top-1、Top-K、无答案正确率、候选数量和耗时；`diagnose_grounding_case()` 把问题归类为 `retrieval`、`generation` 或 `citation`。`owner_id`、`ready` 和 `active_version` 在 SQL 阶段过滤。

无资料时，`rag_grounding.py` 和 Agent system 约束要求明确拒答，不能让模型绕过资料库使用自身知识。

### 文档生命周期层

触发：切块、Embedding、向量写入或版本激活失败。

处理：`document_ingestion.py` 将当前版本标为 `failed`，保留旧的 `ready/active` 版本；只有完整写入后才激活新版本。删除操作由 `DocumentLifecycle.delete()` 在同一事务中处理生命周期和 chunks。

### 写入业务层

触发：模型重复提出创建任务、用户重复确认、提案过期、跨用户确认或并发状态冲突。

处理：`task_proposals.py` 使用 owner 作用域的幂等键、状态条件更新、过期检查和事务。模型只创建 `pending proposal`，确认 API 才能创建 Task。重复确认返回已确认结果，不重复写入。

## 一次真实故障定位示例

曾出现系统日志中看不到业务 JSON 事件的问题。根因不是 Agent 或数据库，而是应用 logger 没有有效 handler，且没有复用 Uvicorn 的父 logger handler。

修复位置：`observability.py` 的 `configure_application_logging()`：

1. 优先查找 `uvicorn.error.handlers`；
2. 没有时查找 `uvicorn.handlers`；
3. 将 handler 绑定到 `study_task` logger；
4. 设置 `propagate=False`，避免重复输出。

修复后的真实请求可以按 `X-Request-ID` 关联 HTTP、Agent、模型和检索日志。例如一次资料问答记录了：

```text
HTTP 总耗时：       2029.727 ms
模型 step 1：       1311.100 ms
知识检索：           15.665 ms / 8.543 ms
模型 step 2：        658.214 ms
```

这说明该请求的主要耗时来自模型阶段，而不是 PostgreSQL 检索。

## 已知限制

- 当前文档 API 接收纯文本，还没有 PDF/Word 解析和后台任务队列；
- 当前评测集适合回归和设计比较，不足以证明大规模数据下的吞吐量；
- RAG 在线测试依赖真实 DeepSeek Key，离线测试使用 MockTransport；
- PostgreSQL 显示 collation version mismatch 警告，需要在升级基础镜像或数据库后刷新 collation version；当前不影响已验证的迁移和事务；
- 页面已通过容器 HTTP 入口验证，但尚未做浏览器自动化兼容性测试；
- 目前是单体 FastAPI 部署，没有异步队列、横向扩展或分布式 tracing。

## 质量结论

当前项目已经具备可演示的 Agent 闭环：认证、用户隔离、RAG、工具白名单、预算、写入确认、幂等、文档版本、结构化日志和 Docker 启动都已有代码和验证证据。项目最重要的质量策略是把模型的不确定性限制在决策层，把身份、权限、事务和资源边界留在服务端。

它还不应被描述成高并发生产系统；更准确的项目表述是：一个经过真实 Compose 联调、带安全边界和失败分层的单体 Agent/RAG 应用。
