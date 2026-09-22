import getpass
import logging
import os
import secrets
import sys
from pathlib import Path

from agent_loop import AgentStepLimitError, run_readonly_agent
from auth import AuthService
from database import Database
from deepseek_api import (
    DeepSeekAPIError,
    DeepSeekConfigurationError,
    DeepSeekNetworkError,
    DeepSeekResponseError,
    DeepSeekSettings,
)
from readonly_tools import ToolArgumentsError, ToolNotAllowedError
from repository import TaskRepository
from service import TaskService


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    default_db = Path(__file__).with_name("tasks.db").resolve().as_posix()
    database_url = os.getenv("DATABASE_URL", f"sqlite+pysqlite:///{default_db}")
    username = input("任务助手用户名: ").strip().lower()
    password = getpass.getpass("任务助手密码: ")
    question = input("问题: ").strip() or "查询我的待完成任务"

    database = Database(database_url)
    try:
        auth = AuthService(
            database.sessions,
            os.getenv("STUDY_TASK_SECRET_KEY") or secrets.token_hex(32),
        )
        token = auth.login(username, password)
        user_id = auth.user_id_for_token(token) if token else None
        if user_id is None:
            print("任务助手用户名或密码错误", file=sys.stderr)
            return 1

        service = TaskService(TaskRepository(database.sessions))
        result = run_readonly_agent(
            question,
            user_id=user_id,
            service=service,
            settings=DeepSeekSettings.from_env(),
        )
    except (
        DeepSeekConfigurationError,
        DeepSeekAPIError,
        DeepSeekNetworkError,
        DeepSeekResponseError,
        AgentStepLimitError,
        ToolArgumentsError,
        ToolNotAllowedError,
    ) as exc:
        print(f"Agent 调用失败: {exc}", file=sys.stderr)
        return 1
    finally:
        database.dispose()

    print(f"回答: {result.answer}")
    print(f"模型请求次数: {result.model_steps}")
    print(f"只读工具调用次数: {result.tool_calls}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
