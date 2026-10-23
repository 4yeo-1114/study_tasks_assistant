# UPG-05 工作台与工程验收

状态：功能验收通过。工作台的 API 合同、真实浏览器操作、移动布局、Canvas 绘制与注入网络失败恢复均已验收；Compose 全链路与在线模型质量仍不在本次结论范围内。

## 工作台数据流

浏览器登录后，前端以 JWT 分别读取 `/tasks`、`/tasks/progress`、`/fitness/progress`、`/documents`、`/plans` 与 `/profile`。界面不接受或保存 `owner_id`；所有数据隔离仍由后端认证依赖和 SQL owner 过滤执行。

总览只负责组合已有确定性数据：任务完成率、累计训练量、动作最高重量、体重周均、待确认计划和资料状态。训练量是全部历史记录的 `Σ 重量×次数`，不标成“本周”，也不推断肌肉或体脂变化。

任务完成时可填写实际分钟，落到原有 `PATCH /tasks/{id}`。训练/体重通过既有接口写入；CSV 保持“预览校验后才可提交”的两阶段操作。资料库展示 document lifecycle；RAG 运行时未启用时，总览保留其它模块并明确显示资料服务不可用。

Agent 页保存服务端返回的 session ID，只用它恢复经 owner 校验的会话；对话答案原文保留来源引用，trace 作为运行诊断展示。Agent 返回的任务提案和周计划提案各自显示确认/拒绝操作，确认前不会创建正式任务。

档案与计划页只调用显式 profile 接口。创建周计划时从当前档案读取 revision/plan_version；计划列表新增 `GET /plans`，仅列出当前 owner 的最近 50 个版本，按创建时间倒序。调整提案会显示服务端生成的 `adjustment_summary`，不由浏览器自行推断用户完成情况。

## 代码定位

- `study_task_assistant/frontend/index.html`：工作台的页面结构和可访问控件。
- `study_task_assistant/frontend/app.css`：桌面/移动布局、状态与图表容器。
- `study_task_assistant/frontend/app.js`：认证请求、视图切换、数据刷新、表单提交和 Canvas 可视化。
- `study_task_assistant/web/api.py`、`weekly_plans/service.py`：`GET /plans` 的认证隔离与排序。
- `tests/test_workbench_flow_api.py`：档案→pending 计划→确认→任务实际用时→训练/体重统计的 API 合同回归。

## 验证证据

- 定向测试：`22 passed, 1 warning in 20.00s`，覆盖前端静态资源、工作台主 API 流、计划、档案、健身 CSV/统计与会话接口。
- 全量 SQLite 回归：`357 tests, 0 failures, 0 errors, 10 skipped, 115.57s`。原始 JUnit：`D:/Temp/upg05-full-junit.xml`。跳过项为需要外部 PostgreSQL 或显式启用在线 DeepSeek 的测试。
- 隔离 PostgreSQL 专项：`9 passed, 1 warning in 7.84s`，报告 `benchmarks/pg_agent_upg04/20261023T033432922510Z/`。已有 checkpoint 场景新增了 `/plans` 的 owner-scoped 读取断言；运行器名称沿用 UPG-04，但临时容器、数据库和源码快照仍独立保存。
- 静态服务探针：`http://127.0.0.1:8010/app/`、`/app/app.css`、`/app/app.js` 均返回 200；该服务使用临时 `D:/Temp/upg05-workbench.db`。
- `node --check study_task_assistant/frontend/app.js` 与 `git diff --check` 通过；后者仅有既有的 LF→CRLF 提示。
- 浏览器 E2E（修复后）：`.venv\\Scripts\\python.exe scripts/run_workbench_e2e.py`，真实 Edge `156.0.4314.42`、独立临时 SQLite、离线桩模型，8 场景 `76/76` 通过，`page_errors=[]`。报告为 `benchmarks/workbench_e2e_upg05/20261023T050209327069Z/`，保留截图、Canvas 像素探针、HTTP 记录与数据库。
- 两个此前由 E2E 发现的缺陷已回归：任务完成的 `actual_minutes=45` 同时通过 UI 与 SQLite 实证；延迟网络下重复 `requestSubmit()` 只产生一轮 Agent 写入，消息数 `4 -> 6`，按钮状态采样为 `[True, True]`。

## 验收边界

- 未验证 Compose 中的 `/app/` 与真实 PostgreSQL/RAG/DeepSeek 链路；在线模型质量、Token 与费用仍单独统计。
- 本轮浏览器使用离线桩模型，用于验证控制流、会话、写入和失败恢复，不代表真实模型质量或线上吞吐。
