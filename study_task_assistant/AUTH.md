# 用户登录和任务隔离

`POST /auth/register` 接收 JSON 用户名和密码；`POST /auth/login` 接收表单字段 `username`、`password`，返回 Bearer 令牌。所有 `/tasks` 接口要求令牌。用户名至少 3 字符，密码至少 8 字符。用户 A 的任务由服务端写入 `owner_id=A.id`，B 即使知道任务 ID，对它执行 GET/PATCH/DELETE 也会得到 404；不带有效令牌返回 401。

本地演示可先运行 `alembic upgrade head`，再启动 `uvicorn api:app --reload`。在 `/docs` 中注册 A、登录 A 并用右上角 Authorize 授权，然后创建任务；改为 B 登录后，列表应为空，访问 A 的任务 ID 应返回 404。`owner_id` 不接受客户端指定。

密码使用 Argon2 哈希保存，不保存明文。访问令牌有效期为 30 分钟。设置 `STUDY_TASK_SECRET_KEY` 为随机生成的至少 32 字节字符串，保证服务重启后旧令牌仍可验证；本地未设置时应用会为当前进程生成临时密钥，重启即失效。多 worker 部署必须让所有进程使用同一密钥。不要提交密钥。可用 `python -c "import secrets; print(secrets.token_hex(32))"` 生成。

当前只用于本地学习。若要开放给外部用户，还需为注册和登录接口加限速，并通过 HTTPS 传输凭据和令牌。

旧数据库里没有归属信息的任务仍保留，但任何新注册用户都看不到。只有确认旧数据确实属于某用户后，才应由数据库管理员进行一次性归属迁移；不要默认分配给第一个注册者。
