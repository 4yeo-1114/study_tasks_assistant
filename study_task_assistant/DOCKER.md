# W5：任务助手的独立 Compose 环境

这套环境使用单独的 `api`、`db` 容器和 `study-task-assistant-w5_postgres_data` 数据卷。它不使用现有 `study-postgres` 容器，也不读取其数据。Windows 访问 API 用 `127.0.0.1:8001`、访问新 PostgreSQL 用 `127.0.0.1:15432`；`api` 容器访问数据库用 `db:5432`。服务名解析和端口含义见 [Docker Compose 网络文档](https://docs.docker.com/compose/how-tos/networking/)。

## 为什么有四个端口数字？

`compose.yaml` 的 `ports` 按 `主机 IP:Windows 端口:容器内端口` 书写。这里有两个**不同程序**：Uvicorn 提供 HTTP API，PostgreSQL 提供数据库服务。

```text
Windows 浏览器/curl → 127.0.0.1:8001 → api 容器的 8000（HTTP）
Windows psql/数据库客户端 → 127.0.0.1:15432 → db 容器的 5432（PostgreSQL）
api 容器 → db:5432（同一 Compose 网络内直接访问数据库服务）
```

设置位置：[`compose.yaml`](compose.yaml) 的 `api.command` 用 `uvicorn ... --port 8000` 指定 API 容器内的监听端口；`api.ports` 把 Windows 的 `8001` 映射过去。`db` 使用的 `postgres:17` 镜像默认在容器内监听 `5432`；`db.ports` 把 Windows 的 `15432` 映射过去。`api.environment.DATABASE_URL` 中的 `@db:5432` 告诉应用向哪个数据库发起连接。`Dockerfile` 也有 Uvicorn 的默认 `CMD`，但当前 Compose 的 `command` 会覆盖它。`api.py` 定义的是应用和路由，不负责设置 Uvicorn 或 PostgreSQL 的监听端口。

Docker Compose 是读取 `compose.yaml`、一次配置并管理多个容器的工具；`services` 是容器化的程序，Compose 会为它们建立网络，`volumes` 保存数据。**应用代码不连接 Docker 引擎**。这里使用 Docker 是为了在隔离、可复现的环境中同时运行 API 和 PostgreSQL，练习容器网络、环境变量与部署；任务助手也能不使用 Docker 运行，例如未设置 `DATABASE_URL` 时使用本地 SQLite。参阅 [Docker 官方 Compose 说明](https://docs.docker.com/compose/intro/compose-application-model/)。

## 第一次准备

在 PowerShell 进入项目目录：

```powershell
cd D:\dev-learning\study_task_assistant
if (-not (Test-Path .env)) { Copy-Item .env.compose.example .env }
```

如果是刚复制的 `.env`，把两个占位值改成不同的随机字符串。可运行两次 `python -c "import secrets; print(secrets.token_hex(32))"` 生成；数据库密码在本练习中使用生成的十六进制字符串，不要包含 URL 特殊字符。本机验证时已经生成过 `.env`，文件存在就不要覆盖它。`.env` 已被 Git 忽略，`.dockerignore` 也不会把它放进镜像。不要把值贴到学习记录或提交到 Git。当前项目代码只读进程环境变量；Compose 读取 `.env` 后通过 `environment` 显式传给容器。参考 [Docker Compose 环境变量文档](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)。

如果本机已经有 Docker Engine 和 PostgreSQL 镜像，执行：

```powershell
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail=80 api
```

`config --quiet` 只检查解析是否成功，不打印包含凭据的完整配置。`up -d --build` 构建 API 镜像并启动两个服务；`db` 健康后，`api` 先运行 `alembic upgrade head`，成功后再启动 Uvicorn。`ps` 看服务状态和端口；`logs` 看迁移/启动报错。构建首次需要拉取 Python 基础镜像，网络较慢时会等待。

浏览器打开 `http://127.0.0.1:8001/docs`。先注册一个新账号，再登录并通过 Authorize 填入访问令牌；创建任务并查询列表。也可以先执行 `curl.exe -i http://127.0.0.1:8001/tasks`，未登录预期得到 401，而不是连接失败。新数据库不会有旧 `study-postgres` 的任务。

## 观察与排错

```powershell
docker compose ps
docker compose logs --tail=80 db
docker compose logs --tail=80 api
docker compose exec db psql -U study -d study_tasks -c "SELECT version_num FROM alembic_version;"
```

预期迁移版本是 `0002_users_and_owners`。若 API 容器不能连接数据库，先看 `db` 是否 healthy，再看 `api` 日志里的错误属于 DNS、TCP、账号密码还是迁移。不要在日志中打印 `DATABASE_URL` 或令牌。把 `DATABASE_URL` 中的 `db` 错写为 `127.0.0.1` 时，`api` 容器会尝试连接自己，因而无法连接数据库；练习完必须恢复。

```powershell
docker compose restart api
docker compose ps
docker compose down
```

`restart api` 用于观察应用重启后数据是否仍在；`down` 停止并移除本套 Compose 的容器和网络，**保留**命名卷中的数据库数据。不要使用 `docker compose down -v`，它会删除本套环境的数据卷。现有 `study-postgres` 不属于本套 Compose 项目。

重启 `api` 后，等 `docker compose ps` 显示它正在运行，再重新登录并查询刚创建的任务，然后才执行 `down`。已创建数据卷后，不要只修改 `.env` 中的数据库密码：PostgreSQL 容器首次初始化时设置的旧密码仍在库中，新连接可能认证失败。

## 本单元验收

1. `docker compose ps` 显示 `db` healthy、`api` running。
2. `/docs` 可打开；未登录 `GET /tasks` 返回 401；注册、登录、创建和查询任务成功。
3. `alembic_version` 为 `0002_users_and_owners`；重启 `api` 后能重新登录并查到任务。
4. 能解释 `127.0.0.1:15432` 与 `db:5432` 各从哪里访问；如果只改主机发布端口，容器间的 `db:5432` 不变。

这些是 W5-02 的目标，尚需实际运行和你的解释后才记为验收通过。
