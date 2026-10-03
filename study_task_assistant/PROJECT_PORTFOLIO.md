# 项目简历与面试材料

## 项目名称

学习任务助手：带 RAG 和工具调用 Agent 的个人学习工作台

## 一句话介绍

一个基于 FastAPI、PostgreSQL/pgvector 和 DeepSeek 的单体 Agent 应用，支持任务管理、用户资料检索、来源引用和需要用户确认的任务创建。

## 简历项目描述

### 精简版

- 设计并参与实现一个基于 FastAPI、JWT、PostgreSQL/pgvector 和 DeepSeek Tool Call 的学习任务 Agent，提供任务管理、资料上传、RAG 问答和 Web 工作台。
- 将混合检索封装为只读 `search_knowledge` 工具，在 SQL 层强制 `owner_id`、`ready` 和 `active_version` 过滤；无证据时阻止模型脱离资料库编造，并要求回答引用 `[来源: source#chunk_id]`。
- 为 `create_task` 建立 proposal/confirmation 流程：模型只生成 `pending` 提案，用户确认后才在事务中写入任务；通过 owner 作用域幂等键、条件更新和预算预检避免重复写入。
- 增加 Agent trace、request ID、模型/检索耗时、候选数和 Token 统计；真实 Compose 联调通过，自动化回归为 `193 passed, 2 skipped, 1 warning`。

### 面试中更准确的贡献表述

本项目采用 AI 工程模式：AI 完成了较多样板实现和测试维护，我重点学习并复核架构、数据流、权限边界、工具调用、故障分类和真实容器联调。面试时应说“参与设计、实现和验证”，不说“全部独立从零开发”。

## 60 秒项目介绍

这是一个学习任务助手，我把它做成了一个带 RAG 的工具调用 Agent。用户先通过 JWT 登录，Agent 收到问题后可以调用只读任务工具，或者调用 `search_knowledge` 从当前用户自己的资料中检索内容。资料使用关键词和 pgvector 混合检索，SQL 阶段会过滤 `owner_id`、`ready` 和当前 active 版本，模型回答必须引用检索来源，没有资料时要明确拒答。

创建任务属于写操作，所以模型不能直接改数据库，只能生成一个 pending proposal，用户调用确认接口后，服务端再次校验用户、状态和过期时间，再在事务中创建任务。为防止模型重复调用，我加了幂等键、工具预算、Token 预算和最大 step。系统还用 `request_id`、`agent_run_id`、`tool_call_id` 记录结构化日志，能够从一次 HTTP 请求追踪到模型和检索阶段。项目已经在 Docker Compose 中真实联调，当前定位是可演示、可排错的单体 Agent/RAG 应用，不是高并发生产系统。

## 三个核心技术难点

### 难点一：如何防止模型越权访问资料

模型只能返回：

```json
{"query": "用户问题", "limit": 3}
```

它不能生成 `owner_id`。`api.py` 通过 `current_user_id()` 从 JWT 得到可信用户身份，然后 `agent_loop.py` 调用：

```python
knowledge_executor.execute(call, owner_id=user_id)
```

`knowledge_tools.py` 再把 owner 传给检索器，关键词和向量两条 SQL 都在数据库层过滤。这样资料在进入模型前就完成隔离，不能依赖模型自觉，也不能先查出所有数据再在 Python 中过滤。

### 难点二：如何避免 Agent 写操作重复执行

`create_task` 不直接插入 `tasks`。Agent 先调用：

```python
proposal_service.propose_from_call(
    user_id,
    call,
    idempotency_key=f"{agent_run_id}:{fingerprint}",
)
```

服务端持久化 `pending proposal`。用户确认时，`TaskProposalService.confirm()` 会检查 owner、状态和过期时间，并在同一个事务中更新提案和创建任务。数据库唯一约束和条件更新共同阻止重复确认和并发覆盖。

### 难点三：如何定位一次 Agent 请求慢在哪里

API 中间件生成 `request_id`，`observability.py` 通过 `ContextVar` 将它传播到深层日志。Agent 另外记录 `agent_run_id`，模型请求记录 step 和耗时，工具记录 `tool_call_id`、候选数和耗时。

一次真实请求的证据：

```text
HTTP 总耗时：       2029.727 ms
模型 step 1：       1311.100 ms
知识检索：           15.665 ms / 8.543 ms
模型 step 2：        658.214 ms
```

因此可以判断主要瓶颈在模型调用，而不是数据库检索。

## 常见面试追问

### 为什么 `owner_id` 必须在 SQL 阶段过滤？

因为 SQL 是资料进入应用和模型之前的第一道数据边界。查询后再过滤会让不属于当前用户的资料已经进入应用内存、缓存、日志或模型上下文，存在泄露风险，也浪费数据库和网络资源。

### 为什么写操作需要 proposal？

模型输出是不可信的决策建议，不等于用户授权。proposal 把“模型想做什么”和“用户确认后实际写入”分成两个阶段，使用户能看到标题、优先级和截止日期，并让服务端在确认时重新校验身份、状态和过期时间。

### 503 和 502 在项目中如何区分？

502 表示已经向 DeepSeek 发出请求，但上游返回错误或响应结构不符合协议；503 表示本地服务暂时不可用，例如缺少 API 配置、PostgreSQL/pgvector 不可用或 Embedding 模型初始化失败。

### 为什么模型请求可以重试，而本地写操作不能随便重试？

模型 HTTP 请求失败时通常没有本地副作用，可以按错误类型有限退避重试。写操作可能已经成功提交，再次执行会重复创建任务，所以必须先有幂等机制；非幂等写入不放进普通 HTTP 重试器。

### 当前项目还有什么限制？

- 文档接口目前接收纯文本，没有 PDF/Word 解析；
- 没有异步任务队列和横向扩展；
- 评测集用于回归和策略比较，不代表大规模生产吞吐；
- 前端是原生 HTML/CSS/JavaScript 工作台，没有独立前端工程；
- PostgreSQL 有 collation version mismatch 警告，需要后续升级基础镜像或刷新数据库 collation；
- 在线模型调用依赖真实 API Key，自动化主回归使用离线替身。

## 面试演示顺序

1. 启动 Compose，打开 `/app/`。
2. 注册并登录一个用户。
3. 上传带唯一短语的资料，展示 `ready` 状态。
4. 通过 Agent 查询资料，展示来源引用和 trace。
5. 请求创建任务，展示 pending proposal。
6. 不确认时刷新任务列表，说明任务数没有变化。
7. 点击确认，说明事务完成写入。
8. 展示 `X-Request-ID` 和容器日志，说明如何定位模型耗时和工具调用。

## 证据文件

- 架构：[ARCHITECTURE.md](ARCHITECTURE.md)
- 质量报告：[QUALITY_REPORT.md](QUALITY_REPORT.md)
- 最终场景：[FINAL_ACCEPTANCE.md](FINAL_ACCEPTANCE.md)
- Docker 说明：[DOCKER.md](DOCKER.md)
- W10 总结：[w10总结.md](../w10总结.md)
