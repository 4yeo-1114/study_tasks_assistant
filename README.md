# Study Task Assistant

一个面向个人学习和训练的 Agent 工作台。用户可以管理学习/健身任务、记录力量训练与体重、保存显式个人档案和周计划，并通过 Agent 查询自己的任务或资料库。

## 核心能力

- JWT 用户认证和用户级任务隔离。
- DeepSeek Agent 工具循环：工具白名单、Pydantic 参数校验、预算和结构化 trace。
- 只读查询与写入提案分离；创建任务必须由用户确认。
- Markdown/TXT 文档导入、文本分块、Embedding、pgvector 和混合检索。
- SQL 阶段过滤 owner_id、ready/active 文档和当前版本，避免越权资料泄露。
- 文档 ready/active/failed 生命周期、失败保留旧版本和并发激活保护。
- Docker Compose 启动 FastAPI、PostgreSQL/pgvector 和 Web 工作台。
- 健身记录闭环：训练场次、动作组、体重记录与确定性进步统计；任务支持学习/健身类型和预计/实际用时。
- CSV 导入支持预览校验与按用户内容哈希幂等提交，重复提交不会重复创建训练记录。
- 持久 Agent 会话、周计划 interrupt/resume 审批、版本冲突检查与结构化 pending 计划提案。
- 工作台提供任务、训练趋势、资料、会话、档案与计划视图；浏览器端到端验收仍在进行。

健身接口：`POST /fitness/workouts` 按日期写入动作组并计算训练量（重量×次数）；`POST /fitness/weight` 按日期写入或幂等更新体重；`GET /fitness/progress` 返回动作训练量、同动作最高重量和体重周均，不据此推断肌肉增长或体脂变化。

## 架构与数据流

```text
Browser -> FastAPI -> Agent Loop -> DeepSeek
                    ├── AuthService / JWT / owner_id
                    ├── TaskService / Repository
                    ├── DocumentService / version lifecycle
                    ├── read-only tools
                    ├── search_knowledge -> HybridRetriever -> PostgreSQL/pgvector
                    └── TaskProposalService -> user confirmation -> Task
```

知识问答时，API 从 JWT 提取可信 user_id，Agent 向模型发送问题和工具 schema；模型返回 tool_calls 后，服务端校验工具名、参数和预算；search_knowledge 在 SQL 阶段按 owner_id、文档状态和活动版本过滤；检索结果携带 source、chunk_id 和正文回传模型；有证据时生成带引用的答案，无证据时拒绝用模型常识冒充资料库答案。

## 安全设计

- 密码只保存哈希，JWT 的 sub 是服务端生成的身份来源。
- 模型不能生成 user_id，也不能绕过工具白名单。
- 写入任务校验 proposal_id、owner_id、状态、过期时间和幂等键。
- 工具参数使用 Pydantic 严格校验。
- API Key、JWT secret、数据库密码只从环境变量读取。

## 目录

```text
study_task_assistant/
├── api.py                      # Uvicorn 启动入口
├── web/                        # HTTP 路由、JWT 认证、请求/响应结构
├── agent/                      # Agent 循环、工具执行、Agent 评测
├── llm/                        # DeepSeek 协议、客户端、工具 schema
├── tasks/                      # 任务业务、仓储、写入提案
├── knowledge/                  # 文档管理、Embedding、检索、RAG 评测
├── storage/                    # 数据库连接、ORM 模型、pgvector SQL
├── core/                       # 结构化日志、重试策略
├── legacy/                     # 早期 CLI 实现
├── examples/                   # 学习演示脚本
├── migrations/                 # Alembic 数据库迁移
├── frontend/index.html         # Web 工作台
├── Dockerfile / compose.yaml
└── requirements.txt
```

职责和代码定位说明见 [模块目录说明](study_task_assistant/MODULE_LAYOUT.md)。业务代码使用明确的包路径导入，例如 `from core.observability import log_event`。本地启动命令继续使用 `api:app`。

## 本地开发

需要 Python 3.10+：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\study_task_assistant\requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn --app-dir study_task_assistant api:app --reload
```

工作台地址为 http://127.0.0.1:8000/app/，Swagger 地址为 http://127.0.0.1:8000/docs。本地 SQLite 适合测试 API；生产 RAG 需要 PostgreSQL + pgvector。

## Docker Compose

```powershell
cd .\study_task_assistant
Copy-Item .env.compose.example .env
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

Compose 会启动 PostgreSQL/pgvector、Alembic 迁移、FastAPI 和 FastEmbed 模型缓存。工作台地址为 http://127.0.0.1:8001/app/，Swagger 地址为 http://127.0.0.1:8001/docs。个人演示适合单体 Docker Compose + 托管 PostgreSQL/pgvector，当前项目规模不需要 Kubernetes。

UPG-04 / UPG-05 实现边界与验收证据见 [UPG-04 持久 Agent 验收](docs/UPG04持久Agent验收.md) 和 [UPG-05 工作台验收](docs/UPG05工作台工程验收.md)。

## 测试与质量

tests/ 覆盖认证、任务、提案、Agent 循环、工具校验、RAG、向量/关键词/混合检索、文档生命周期、并发保护、API 和前端静态入口。

公开仓库测试集最近一次验证：171 passed, 2 skipped, 1 warning。学习阶段的 demo 专用测试已从公开仓库移除；真实 PostgreSQL 集成测试只有设置 TEST_DATABASE_URL 时运行。

## 项目亮点与改进点

- SQL 阶段 owner_id 过滤，防止跨用户资料泄露。
- 工具白名单和 Pydantic 校验，限制模型行为边界。
- 创建任务先生成 pending proposal，用户确认后才写入。
- 答案引用 source/chunk_id；无证据时拒答，减少幻觉。
- 新版本失败时保留旧 active 版本，条件更新保护并发激活。
- trace 记录状态、工具名、调用 ID、耗时和候选数量。
- 模型步数、Token、工具调用和知识检索次数均有预算。

## 简历项目描述

> 独立开发基于 FastAPI、DeepSeek、PostgreSQL/pgvector 的个人知识库 Agent 工作台，构建“文档导入—文本分块—Embedding—混合检索—证据约束生成”的 RAG 链路；通过 JWT + SQL owner_id 过滤实现用户级任务与资料隔离，设计只读工具与写入提案确认机制，并加入幂等键、模型步数/Token/工具调用预算、重试策略和结构化 trace，降低重复写入与越权访问风险；实现文档 ready/active/failed 生命周期、失败保留旧版本和并发激活保护，支持 Markdown/TXT 上传、来源引用和空证据拒答；使用 Docker Compose 完成 FastAPI、PostgreSQL/pgvector 和 Web 工作台部署，当前自动化测试 196 项通过。

## 当前限制

- 当前面向个人和小规模演示，尚未提供后台任务队列和多副本部署。
- 真实模型质量和检索准确率需要在目标资料集上继续评测。
- 生产环境还应补充 HTTPS、数据库备份、限流、监控告警和密钥托管。
