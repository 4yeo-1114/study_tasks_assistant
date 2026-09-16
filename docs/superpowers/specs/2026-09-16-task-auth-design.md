# 学习任务助手：最小认证与任务隔离

## 目标

同一服务支持多个用户。未登录者不能操作任务；登录用户只能读取、创建、修改和删除自己的任务。用户不能通过请求体指定 `owner_id`。

## 方案比较与选择

- HTTP Basic 每次请求带密码，改动少，但不适合作为本项目后续 Agent 工具身份上下文。
- 数据库存储随机会话令牌便于撤销，但要多一张令牌表和清理流程。
- 采用 FastAPI 文档所用的密码哈希与短期 Bearer JWT：注册保存 Argon2 密码哈希，登录签发 30 分钟令牌，受保护接口验证令牌并查询用户。服务重启后令牌要继续有效时需设置持久的 `STUDY_TASK_SECRET_KEY`；未设置时本地开发进程使用临时密钥。

## 数据与接口

- Alembic 新版本创建 `users(id, username, password_hash)`，并给 `tasks` 增加可空的 `owner_id` 和索引。已有无归属任务保留为 NULL，不对新用户可见；不自动声称它们属于第一个注册者。
- `POST /auth/register` 接收用户名和密码；重复用户名返回 409；响应不包含密码哈希。
- `POST /auth/login` 使用 OAuth2 表单字段 `username`、`password`，成功返回 Bearer 令牌；凭据错误返回 401。
- 所有 `/tasks` 路由要求有效 Bearer 令牌。缺失/无效令牌返回 401。跨用户按任务 ID 访问返回 404；列表只含自己的任务；创建时 owner_id 从认证上下文注入。
- 用户名去首尾空白、转小写；长度 3～32。密码长度 8～128。登录失败不区分不存在用户和密码错误。

## 数据流与验证

请求 → API 的认证依赖 → AuthService 验证令牌与用户 → TaskService 传 user_id → Repository 按 owner_id 过滤 → 数据库。

验收用两个用户：A 创建任务，B 列表为空，B 对 A 的任务 GET/PATCH/DELETE 均 404 且 A 的任务未变化，A 自己可操作；缺失/无效令牌 401；注册和登录错误覆盖。SQLite 与专用 PostgreSQL 测试库均运行迁移。旧数据行数与内容保留。
