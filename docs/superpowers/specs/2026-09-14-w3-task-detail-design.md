# W3-AI-02 单条任务查询设计

## 目标与接口

新增 `GET /tasks/{task_id}`。任务存在时返回符合 `TaskRead` 的任务和 `200`；任务不存在时返回 `404` 与 `{"detail": "找不到任务"}`；`task_id` 不是整数或小于 1 时由 FastAPI/Pydantic 返回 `422`。

`{task_id}` 是路径参数。它与 `GET /tasks?status=pending` 的查询参数不同：路径参数用于定位一个具体资源，查询参数用于筛选资源集合。

## 分层与数据流

1. `api.py` 使用 `Annotated[int, Path(ge=1)]`声明路径参数并注册路由。
2. FastAPI 在进入路由函数前把路径文本转换成整数并检查大于等于 1。
3. `TaskService.get_task(task_id)` 组织单条查询用例。
4. `repository.get_task(db_path, task_id)` 使用 `WHERE id = ?` 查询 SQLite，返回任务字典或 `None`。
5. API 将 `None` 转换为 `HTTPException(404)`；成功结果由 `TaskRead` 校验并序列化。

HTTP 错误只在 API 层产生，Repository 不依赖 FastAPI。

## 测试与范围

- 先创建任务，再请求 `/tasks/1`，验证 `200` 和完整 JSON。
- 请求 `/tasks/999`，验证 `404` 和固定 detail。
- 请求 `/tasks/not-an-int` 与 `/tasks/0`，验证 `422`。
- 运行现有全部测试，确保集合查询、status 筛选和 POST 不回归。

本单元不增加更新、删除、认证或 ORM，不修改现有任务数据结构。
