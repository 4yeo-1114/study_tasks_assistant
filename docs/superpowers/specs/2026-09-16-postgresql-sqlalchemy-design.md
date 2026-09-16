# PostgreSQL 与 SQLAlchemy 迁移设计

## 目标

将学习任务助手的数据层从直接调用 `sqlite3` 迁移到 SQLAlchemy 2.0，使同一套 Repository 能在测试中使用 SQLite、在实际服务中使用 PostgreSQL。此次只完成连接配置、连接生命周期、连接池和现有任务 CRUD；schema 版本迁移、认证和用户隔离放到后续单元。

完成后，现有 API 行为和状态码保持不变。用户能够解释 `API → Service → Repository → Session → Engine/连接池 → PostgreSQL` 的数据流，并能依据异常定位一次错误端口造成的连接失败。

## 方案选择

采用同步 SQLAlchemy 2.0 ORM 和 psycopg 3 驱动。

该方案让 SQLite 单元/API 测试和 PostgreSQL 实际运行共享模型与 Repository，避免维护两套 CRUD。同步调用也与现有同步 FastAPI 路由一致。当前不引入异步数据库驱动，因为它会同时增加 async、连接池和测试复杂度，而本单元的目标是数据库工程基础。

不采用先写 psycopg CRUD 再迁移 ORM 的方案，因为会产生一次完整重写；也不保留并行的 SQLite/PostgreSQL Repository，因为当前规模下重复实现没有足够收益。

## 模块边界

### `database.py`

- 接受 SQLAlchemy database URL 并创建 `Engine`。
- 为 SQLite 测试设置必要的线程连接参数；PostgreSQL 使用 SQLAlchemy 默认的 `QueuePool`。
- 创建 `sessionmaker`，每个 Repository 操作获得独立 `Session`。
- 提供建表和释放 Engine 连接池的方法。

### `models.py`

- 使用 SQLAlchemy declarative model 定义 `Task` 和 `tasks` 表。
- 字段保持 `id`、`title`、`status`、`priority`、`due_date`。
- `status` 和 `priority` 保留数据库 `CHECK` 约束。
- `due_date` 使用数据库 `DATE` 和 Python `date`；API JSON 仍输出 `YYYY-MM-DD`。

### `repository.py`

- 改为 `TaskRepository`，构造时接收 session factory。
- 每个公开方法自行控制一个短生命周期 Session。
- 查询使用 SQLAlchemy `select()`；创建、更新和删除在成功时提交，异常时由 Session 上下文回滚。
- 返回普通字典，保持 Service 和 API 当前契约，暂不让 ORM 对象跨出 Repository。

### `service.py`

- 构造时接收 `TaskRepository`，不再持有文件路径。
- 保留现有业务方法与 Pydantic 输入类型。
- 不负责创建表、打开连接或提交事务。

### `api.py`

- `create_app()` 接受 database URL，组装 Engine、Session factory、Repository 和 Service。
- 模块级 `app` 从 `DATABASE_URL` 环境变量读取实际配置；缺失时保留本地 SQLite URL，避免导入模块即失败。
- 应用关闭时调用 `engine.dispose()` 释放连接池。
- 路由、响应模型和 HTTP 状态码保持不变。

## 配置与凭据

- 新增 `.env.example`，只包含无真实密码的 URL 格式示例。
- `.gitignore` 忽略 `.env`。
- 本地 PostgreSQL URL 形如 `postgresql+psycopg://USER:PASSWORD@127.0.0.1:5432/study_tasks`。
- 生产连接使用 `DATABASE_URL`；集成测试只接受单独的 `TEST_DATABASE_URL`，禁止回退到生产 URL。
- 不在源代码、测试输出、学习日志或提交中记录真实密码。

## 数据流与事务

创建任务时：FastAPI/Pydantic 校验请求 → Service 调用 Repository → Repository 从 session factory 获取 Session → Session 从 Engine 连接池借连接 → 执行 INSERT → commit → refresh 得到数据库生成的 ID → 转为字典 → API 按 `TaskRead` 序列化。

读取操作在短 Session 内执行 SELECT。写操作只有 commit 后才持久化；SQLAlchemy 异常会退出事务上下文并回滚。Session 用完关闭，将底层连接归还连接池，而不是每次销毁 TCP 连接。

## 测试设计

1. 先新增一个 Repository 行为测试，要求 SQLAlchemy Repository 在临时 SQLite 中完成创建和读取；在实现前确认测试因模块/接口不存在而失败。
2. 迁移实现后运行现有 API 测试，确保当前实测的 22 个行为不回归。测试显式传入临时 SQLite database URL，不依赖开发环境变量。
3. 新增 opt-in PostgreSQL 集成测试，只在设置 `TEST_DATABASE_URL` 时运行；目标是专用 `study_tasks_test` 数据库。测试建表、清理、创建和读取，不操作练习表或实际应用数据库。
4. 手工启动服务，以 `DATABASE_URL` 连接 `study_tasks`，通过 HTTP 创建任务并在 psql 查询 `tasks` 表核对。
5. 将测试 URL 端口改成一个未监听端口，保留完整异常类型与关键错误，用户据此指出失败发生在 Repository 建立数据库连接之前/期间，而不是 HTTP 路由校验。

## 验收标准

- 现有 API 测试全部通过，响应 JSON 和状态码不变。
- SQLAlchemy Repository 行为测试通过。
- 专用 PostgreSQL 集成测试通过，且不会清理或修改 `study_tasks` 实际数据。
- 实际 FastAPI 服务能通过 PostgreSQL 完成 POST 和 GET，并由 psql 验证同一行。
- `.env` 被忽略，仓库中没有数据库密码。
- 用户能解释 Engine、连接池、Session、commit/rollback 的职责，以及错误端口为何属于连接故障。

## 后续范围

本设计完成后再引入 Alembic，把 `create_all()` 替换为显式 schema migration；随后添加用户表、认证上下文和 owner 外键，验收用户 A 无法读取或修改用户 B 的任务。本单元不实现这些内容。
