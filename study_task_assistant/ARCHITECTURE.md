# 学习任务助手架构

## 项目定位

这是一个带 RAG 和工具调用 Agent 的学习任务助手。用户可以管理任务、上传个人资料，并通过自然语言查询任务或资料。只读操作可以由 Agent 自动执行；创建任务等写操作先生成提案，必须经过用户确认后才会修改数据库。

## 运行时组件

```text
浏览器 / curl / 前端
          |
          v
FastAPI
  |-- JWT 认证：从 token 的 sub 得到 user_id
  |-- /tasks：任务 CRUD
  |-- /documents：资料上传、查询、删除
  `-- /agent/chat：Agent 入口
          |
          v
Agent Loop
  |-- DeepSeek：决定是否调用工具、组织最终回答
  |-- 只读任务工具：查询 tasks
  |-- search_knowledge：混合检索当前用户资料
  `-- create_task：创建 pending proposal
          |
          +--> PostgreSQL + pgvector
          |      `-- tasks / task_proposals / documents / document_chunks
          |
          `--> 结构化日志
                 `-- request_id / agent_run_id / step / tool_call_id
```

## 模块职责

| 模块 | 关键文件 | 职责 |
|---|---|---|
| API 与认证 | `api.py`, `auth.py` | 解析 HTTP 请求、校验 JWT、注入可信 `user_id`、映射错误状态码 |
| 任务业务 | `service.py`, `repository.py` | 任务的查询、创建、完成和删除 |
| Agent 编排 | `agent_loop.py` | 管理消息历史、模型 step、工具调用、预算、停止条件和 trace |
| 工具定义 | `deepseek_tools.py`, `knowledge_tools.py`, `readonly_tools.py` | schema、白名单、参数校验和本地执行 |
| 写入确认 | `task_proposals.py` | pending/confirmed/rejected 状态、幂等和确认事务 |
| RAG 检索 | `keyword_retrieval.py`, `embedding_retrieval.py`, `hybrid_retrieval.py` | 关键词、向量和融合排序 |
| 文档入库 | `document_service.py`, `document_ingestion.py`, `document_lifecycle.py` | 文档状态、版本、切块、Embedding、向量写入和删除 |
| 数据存储 | `database.py`, `models.py`, `pgvector_store.py` | SQLAlchemy Session、ORM 模型和 pgvector SQL |
| 生产组装 | `knowledge_runtime.py` | 共享模型/检索器，按请求创建有状态工具执行器 |
| 观测 | `observability.py` | request ID 传播、JSON 日志、耗时和错误类型 |

## Agent 请求数据流

### 只读知识问答

```text
POST /agent/chat
  -> OAuth2PasswordBearer 读取 Authorization
  -> auth.user_id_for_token() 验证签名、过期时间和 sub
  -> agent_runner(message, user_id=可信身份)
  -> DeepSeek 返回 search_knowledge tool_call
  -> KnowledgeToolExecutor 校验工具名和 query/limit
  -> 服务端注入 owner_id
  -> 关键词 SQL + pgvector SQL 在数据库层过滤 owner/ready/active
  -> 返回 source、chunk_id、text、score
  -> 以 tool message 和原始 tool_call_id 回传模型
  -> DeepSeek 返回 stop 和最终回答
```

模型只提供 `query` 和 `limit`。`owner_id`、数据库 Session 和权限条件由服务端决定，不能由模型生成。

### 创建任务

```text
DeepSeek 返回 create_task tool_call
  -> Agent 校验工具名、参数和工具预算
  -> TaskProposalService.propose_from_call()
  -> 保存 pending proposal，不写入 tasks
  -> tool message 返回 proposal_id 和任务内容
  -> Agent 告诉用户需要确认
  -> 用户调用 /agent/task-proposals/{id}/confirm
  -> 服务端重新验证 owner、状态和过期时间
  -> 同一事务中确认 proposal 并创建 Task
```

`tool_call_id` 只标识模型的一次工具调用；`proposal_id` 标识数据库中的业务提案，二者不能混用。

## 权限边界

所有用户身份均来自 JWT：

```text
Authorization header
  -> OAuth2PasswordBearer
  -> auth.user_id_for_token()
  -> API/Agent 的 user_id
  -> SQL WHERE owner_id = :owner_id
```

`owner_id` 不从请求 body、工具参数或模型输出中读取。这样可以在资料进入模型之前阻断跨用户数据，避免“先查出再过滤”的泄露风险。

## 文档生命周期

```text
上传
  -> pending
  -> processing
  -> 切块 + embedding + 写入当前版本
  -> ready，并切换 active_version

失败
  -> failed
  -> 保留原来的 ready/active 版本

删除
  -> 在同一事务中删除生命周期记录和对应 chunks
```

检索 SQL 同时检查：

```sql
owner_id = :owner_id
AND state = 'ready'
AND document_version = active_version
```

因此半成品、失败版本和旧的非 active 版本不会进入 RAG 上下文。

## 状态、预算与失败处理

Agent 状态大致为：

```text
received -> deciding -> tool_calling -> validating -> executing
         -> deciding -> answering -> completed
```

关键限制：

- `max_model_steps` 限制模型决策轮数；
- `max_tool_calls` 限制工具总调用次数；
- `max_total_tokens` 限制模型 Token 总量；
- 模型 HTTP 请求可以按策略有限重试；
- 本地工具执行不放进模型 HTTP 重试器，避免重复副作用；
- 写操作必须先提案，确认后才进入事务。

API 错误映射：

| 情况 | 状态码 |
|---|---:|
| JWT 无效或过期 | 401 |
| 工具名/参数不合法 | 422 |
| 提案幂等冲突 | 409 |
| Agent 预算或步数耗尽 | 429 |
| DeepSeek 上游失败 | 502 |
| 本地模型/RAG 运行时不可用 | 503 |

## 可观测性

`observability.py` 使用 `ContextVar` 保存当前 HTTP 请求的 `request_id`。深层模块调用 `log_event()` 时会自动带上它。

日志关联层次：

```text
request_id       一次 HTTP 请求
agent_run_id     一次 Agent 循环
step             一轮模型决策
attempt          同一模型请求的重试次数
tool_call_id     一次工具提案/结果配对
proposal_id      一条持久化写入提案
```

日志记录事件、状态、耗时、Token、候选数量和错误类型；不记录 API Key、JWT、完整问题、工具参数或文档正文。

## 部署边界

Compose 运行两个服务：

```text
Windows -> 127.0.0.1:8001 -> api:8000
api     -> db:5432          -> PostgreSQL + pgvector
```

`api` 容器启动时先执行 `alembic upgrade head`，迁移成功后启动 Uvicorn。PostgreSQL 数据保存在命名卷，FastEmbed 模型缓存保存在 `fastembed_cache` 命名卷。

## 当前限制

- 当前接口接收纯文本资料，还没有文件解析和异步任务队列；
- 混合检索和评测集适合学习项目，尚未针对大规模数据做容量压测；
- 客户端没有独立前端，提案确认可通过 `/docs` 或 HTTP 客户端完成；
- W11 的目标是整理和演示已有闭环，不再引入复杂多 Agent 或微服务架构。
