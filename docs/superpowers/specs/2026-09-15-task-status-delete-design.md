# 任务状态更新与删除接口设计

## 目标

为学习任务助手增加状态更新和删除接口，用最小功能学习 PATCH、DELETE、请求体校验、204 响应及跨层数据流。首版只允许更新任务状态，不扩展标题、优先级和截止日期更新。

## 接口契约

### PATCH /tasks/{task_id}

- 路径参数 `task_id` 必须是大于等于 1 的整数；不合法时由 FastAPI 返回 422。
- 请求体格式为 `{"status": "pending"}` 或 `{"status": "completed"}`。
- 请求体由 Pydantic 模型 `TaskStatusUpdate` 校验；状态只能是 `pending` 或 `completed`。
- 更新成功返回 200，响应体符合 `TaskRead`。
- 任务不存在返回 404，响应体为 `{"detail": "找不到任务"}`。
- 重复提交当前状态仍返回 200 和当前任务，操作具有幂等性。

### DELETE /tasks/{task_id}

- 路径参数采用与单条查询和 PATCH 相同的正整数约束。
- 删除成功返回 204，响应体为空。
- 任务不存在返回 404，响应体为 `{"detail": "找不到任务"}`。

## 分层职责与数据流

`schemas.py` 定义 `TaskStatus` 和 `TaskStatusUpdate`，只负责请求数据结构与状态值校验。

`api.py` 注册 PATCH 和 DELETE 路由，接收并校验 HTTP 输入，调用 Service，将不存在的结果转换成 404。API 不直接编写 SQL。

`service.py` 提供 `update_task_status(task_id, task_status)` 和 `delete_task(task_id)`，初始化数据库并组织 Repository 调用。首版没有额外业务规则。

`repository.py` 使用参数化 SQL：UPDATE 根据 ID 更新状态并读取更新后的任务；DELETE 根据 ID 删除并通过受影响行数判断是否存在。所有写操作显式提交事务。

PATCH 数据流：客户端 → FastAPI 路由与 Pydantic → TaskService → Repository → SQLite → TaskService → `TaskRead` 响应。

DELETE 数据流：客户端 → FastAPI 路径校验 → TaskService → Repository → SQLite → 204 或 404 响应。

## 错误处理

- 非整数、0 或负数 ID：422，业务函数不会执行。
- PATCH 请求体缺少 status 或状态不在允许范围：422，数据库不会写入。
- 合法 ID 但数据库中不存在任务：Repository 返回 `None` 或 `False`，API 转换成 404。
- 未预期的数据库异常不伪装成 404，继续作为 500 暴露给日志和测试定位。

## 测试范围

- 创建任务后 PATCH 为 completed，断言 200、响应状态和随后 GET 的持久化结果。
- 对同一任务重复 PATCH completed，断言仍为 200 且结果不变。
- PATCH 非法状态，断言 422，并确认原任务仍为 pending。
- PATCH 不存在 ID，断言业务 404。
- DELETE 已存在任务，断言 204、空响应体，并确认随后 GET 返回 404。
- DELETE 不存在 ID，断言业务 404。
- PATCH 和 DELETE 的 0、非整数 ID 由现有路径约束模式覆盖。
- 最后运行全部 pytest，现有 GET、POST 和筛选行为不得回归。

## 学习者验收

AI 编写 Pydantic 模型、三层 CRUD 样板和基础测试。学习者需要完成：

1. 按 PATCH 请求数据流解释每层接收和返回的值。
2. 解释 200、204、404、422 在本功能中的区别。
3. 独立补充“重复完成任务仍返回 completed”的接口测试并运行全部测试。

第 3 项作为 HTTP/FastAPI L4 的候选证据；如果最终测试需要 AI 修改，则保留为 L3，并在后续变式复核。
