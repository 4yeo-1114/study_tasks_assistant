# 学习任务助手

## 项目介绍

一个基于 Python、SQLite 和 FastAPI 的学习任务管理项目。当前同时提供命令行程序和最小 HTTP API。

## 环境

需要 Python 3.10 及以上。在项目根目录 `D:\dev-learning` 打开终端：

```text
python -m venv .venv
.\.venv\Scripts\activate
.\.venv\Scripts\python.exe -m pip install -r .\study_task_assistant\requirements.txt
```

激活失败时，也可以不激活，直接用虚拟环境里的解释器运行（下一节）。

## 运行

在项目根目录执行：

```text
.\.venv\Scripts\python.exe .\study_task_assistant\main.py
```

或先进入目录再运行：

```text
cd .\study_task_assistant
..\.venv\Scripts\python.exe .\main.py
```

更常见的是激活虚拟环境后：

```text
cd .\study_task_assistant
python main.py
```

启动后输入 `help` 查看命令。

## HTTP API

在项目目录启动 FastAPI：

```text
cd .\study_task_assistant
..\.venv\Scripts\python.exe -m uvicorn api:app --reload
```

浏览器打开 `http://127.0.0.1:8000/docs` 可以查看并调用自动生成的接口文档。

查询全部任务：

```powershell
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8000/tasks
```

新增任务：

```powershell
$body = @{title="学习 FastAPI"; priority="high"} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/tasks -ContentType "application/json" -Body $body
```

当前接口：

- `GET /tasks`：返回任务数组，成功状态码为 `200`；可使用 `?status=pending` 或 `?status=completed` 筛选。
- `POST /tasks`：校验 JSON 并新增任务，成功状态码为 `201`。
- 请求字段不合法时返回 `422`；路径不存在时返回 `404`。

`schemas.py` 中的 Pydantic 模型声明请求和响应的数据格式。FastAPI 使用它校验 JSON、生成错误信息和接口文档。

## 可用命令

```text
add <标题>              新增任务
list                   列出全部任务
get <编号>              查看指定任务
complete <编号>         标记为已完成
delete <编号>           删除任务
help                   查看命令
quit                   退出
```

非法编号、未知命令、空标题会提示错误，程序不会退出。

## 数据存储

任务保存在 `study_task_assistant/tasks.db`（与 `main.py` 同一目录），用 SQLite。

- 文件不存在：程序会自动建库建表，当作还没有任务。
- 增删改后写回数据库；关掉再打开，列表应与上次一致。

API 测试使用 pytest 临时目录中的独立数据库，不修改 `tasks.db`。运行全部测试：

```text
cd .\study_task_assistant
..\.venv\Scripts\python.exe -m pytest -v
```
