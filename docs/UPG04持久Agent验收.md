# UPG-04 持久 Agent：实现与验收

状态：构建完成，待用户 / Claude 阶段验收。实现与自动化验证由 Codex 完成，不作为用户独立修改或测试能力证据。

## 主数据流

`JWT → 会话与运行记录 → 历史消息/显式档案 → Agent 白名单工具 → pending 周计划 → LangGraph interrupt → 用户确认 → Command(resume) → SQL 事务写任务与版本 → checkpoint`

聊天通过 `get_planning_context` 读取档案、任务完成统计和训练趋势；`propose_weekly_plan` 只生成提案，服务端填充 owner、档案 revision、计划版本与幂等键。`propose_plan_adjustment` 依据真实记录生成下周调整提案。工具白名单没有确认或档案写入工具，模型不能自行授权。缺少每日预算、训练频次时要求补档案，不虚构记录。

会话、消息、运行和计划按认证身份隔离。聊天请求支持 `session_id` 与可选 `idempotency_key`，响应返回 session/run ID 和结构化 `pending_plans`。相同幂等键只复用相同计划内容，不意味着整个聊天请求只调用一次模型。

## 关键代码

- `study_task_assistant/agent/planning_tools.py`：模型参数与服务端权限/版本边界。
- `study_task_assistant/agent/plan_approval.py`：review 暂停、apply 恢复与失败重试。
- `study_task_assistant/agent/persistent_runtime.py`、`session_store.py`：官方 SQLite/PostgreSQL saver 与会话运行持久化。
- `study_task_assistant/weekly_plans/service.py`：预算/日期/频次、版本、事务、幂等和实际记录调整。
- `study_task_assistant/web/api.py`：认证、错误码和响应组装。

## 接口与失败分支

| 接口 | 行为 |
|---|---|
| `GET/PUT/DELETE /profile` | 用户显式管理档案，不把任意对话自动存成事实 |
| `POST /agent/chat`、`GET /agent/sessions/{id}` | 多轮历史、运行状态；跨用户 ID 返回 404 |
| `POST /plans/weekly`、`POST /plans/{id}/adjust` | 生成 pending 提案；确认前不创建正式任务 |
| `GET /plans/{id}/workflow` | 查询是否仍等待用户决定 |
| `POST /plans/{id}/confirm`、`reject` | 恢复审批图，事务应用或拒绝；重复同决定幂等 |

确认重新检查档案和计划版本，过期返回 409。并发确认使用 SQL 行锁和版本检查，整批写入失败则回滚；checkpoint 中保留决定以便同决定重试。过期确认失败后允许明确拒绝 pending 提案，避免永久悬挂。数据库若已提交而最终 checkpoint 写失败，重试以 SQL 状态为准，避免重复写任务。

阶段验收后的并发补强：周计划创建继续由 `(owner_id, idempotency_key)` 唯一约束裁决；败方在 savepoint 内处理 `IntegrityError`，回读胜方并校验 payload hash，不同 payload 仍冲突。会话在 `agent_sessions.message_sequence` 上用 `UPDATE ... RETURNING` 原子分配每轮两个序号；迁移 `0017_agent_message_sequence` 从已有 `agent_messages` 最大序号回填，避免历史序号被覆盖。PG 同步屏障测试稳定复现原先两种唯一键冲突，修复后并发专项通过。

interrupt 节点恢复时会重新执行，因此 review 中没有业务写入；写入集中在 apply 并依赖事务幂等。参考 [LangGraph 官方 interrupt 文档](https://docs.langchain.com/oss/python/langgraph/interrupts)。审批 thread 由服务端构造，访问 checkpoint 前先校验 SQL owner；同 app 图操作串行，跨进程业务正确性依赖数据库。

## 证据与复现

从仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe scripts/run_agent_scenarios.py
.\.venv\Scripts\python.exe scripts/run_pg_agent_acceptance.py --full-suite
```

场景集：78 个行为场景 + 1 个完整性检查，79 passed。原始证据在 `benchmarks/agent_scenarios_upg04/20261022T100215486750Z/`；该报告早于最后的“过期确认后拒绝”修复，最终源码以 PG 全量报告快照为准。

此前阶段验收 PG 全量：**351 passed, 1 skipped, 1 warning，141.21s**。补入同幂等键 create 竞争恢复、原子消息序号与 0017 迁移后，最新全量为 **354 passed, 1 skipped, 1 warning，5180.37s**，报告 `benchmarks/pg_agent_upg04/20261022T124305467676Z/`，exit_code=0、source_unchanged_during_run=true。耗时受本机并行/容器资源影响，不作为性能指标。运行器保存源码 ZIP、SHA-256、HEAD/dirty、镜像 ID、Python、命令、JUnit 和 stdout/stderr。

## 边界

- 模型为确定性 MockTransport，不证明在线生成质量、真实 Token 费用或性能改善；在线验收单独统计。
- 自动检查日期、每日分钟预算、训练频次；任意自然语言偏好和限制仍需用户复核，不称为已自动执行全部约束。
- 档案只支持用户显式修改，尚无独立的“模型档案修改提案”流程。
- 已验证审批点暂停、重开恢复和失败重试；没有恢复在途模型 HTTP 请求。未验证多进程同时操作同一 checkpoint thread。
- 工作台的会话、计划差异和确认体验及浏览器流程留给 UPG-05；UPG-03 批量入库吞吐仍未测量。
- 现有持久 PG 卷出现 collation 版本不匹配，本轮不重置业务库，采用临时容器完成隔离验收。
