# 业务模块目录说明

根目录 `api.py` 是 Uvicorn 入口，只导出应用工厂和应用对象；实际路由在 `web/api.py`。

| 目录 | 主要模块 | 查找内容 |
|---|---|---|
| `web/` | `api.py`, `auth.py`, `schemas.py` | HTTP 路由、认证依赖、请求与响应结构、错误映射 |
| `agent/` | `agent_loop.py`, `readonly_tools.py`, `knowledge_tools.py`, `agent_evals.py` | 模型决策循环、工具参数校验、预算、工具结果回传、trace |
| `llm/` | `deepseek_api.py`, `deepseek_client.py`, `deepseek_tools.py`, `model_client.py` | 模型配置、HTTP/SSE 协议、工具 schema、响应解析 |
| `tasks/` | `service.py`, `repository.py`, `task_proposals.py` | 任务业务、任务查询、提案确认、事务与幂等 |
| `knowledge/` | `document_service.py`, `document_ingestion.py`, `document_lifecycle.py` | 文档导入、切块、版本状态、激活、删除 |
| `knowledge/` | `embedding_retrieval.py`, `keyword_retrieval.py`, `hybrid_retrieval.py`, `retrieval_strategy.py` | 向量化、检索和融合排序 |
| `knowledge/` | `knowledge_runtime.py`, `rag.py`, `rag_grounding.py`, `retrieval_eval.py` | 运行时组装、上下文、证据约束、检索评测 |
| `storage/` | `database.py`, `models.py`, `pgvector_store.py`, `migration.py`, `legacy_sqlite_migration.py` | 连接池、Session、表定义、向量 SQL、迁移辅助 |
| `core/` | `observability.py`, `reliability.py` | 请求 ID、日志输出、错误重试策略 |
| `legacy/` | `main.py` | 早期 CLI 与 SQLite 学习实现 |
| `examples/` | 各类 demo | 单模块演示；不参与生产镜像 |
| `frontend/` | `index.html` | 浏览器工作台 |

## 请求链路

```text
api.py -> web/api.py
            -> web/auth.py
            -> agent/agent_loop.py -> llm/deepseek_tools.py
                    -> agent/readonly_tools.py -> tasks/service.py
                    -> agent/knowledge_tools.py -> knowledge/hybrid_retrieval.py
                    -> tasks/task_proposals.py
            -> knowledge/document_service.py -> knowledge/document_ingestion.py
业务服务 -> storage/ 的 ORM、Session 和 SQL
日志与重试 -> core/
```

这次只调整模块位置、导入和资源定位，保留既有 API、函数接口及事务逻辑。`web/api.py` 仍集中组装路由，尚未拆成多个 APIRouter；`knowledge/` 也暂不继续嵌套，方便按文件名定位。

## 启动与导入

在仓库根目录启动：

```powershell
.\.venv\Scripts\python.exe -m uvicorn --app-dir study_task_assistant api:app --reload
.\.venv\Scripts\python.exe -m pytest -q
```

在 `study_task_assistant/` 中启动：

```powershell
python -m uvicorn api:app --reload
python -m examples.agent_loop_demo
python -m legacy.main
```

导入使用包路径，例如 `from storage.database import Database`；不要直接运行包内文件（如 `python agent/agent_loop.py`）。Alembic 从 `storage.models` 读取模型，迁移文件仍位于 `migrations/`。Dockerfile 显式复制生产包和前端。
