import json
import logging
import os
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Sequence
from typing import Iterator


_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def configure_application_logging(
    level_name: str | None = None,
    *,
    handlers: Sequence[logging.Handler] | None = None,
) -> None:
    configured = (level_name or os.environ.get("STUDY_TASK_LOG_LEVEL", "INFO")).upper()
    level = getattr(logging, configured, None)
    if not isinstance(level, int):
        raise ValueError("STUDY_TASK_LOG_LEVEL 不是合法日志级别")
    application_logger = logging.getLogger("study_task")
    application_logger.setLevel(level)
    if handlers is not None:
        selected_handlers = list(handlers)
    else:
        selected_handlers = list(logging.getLogger("uvicorn.error").handlers)
        if not selected_handlers:
            selected_handlers = list(logging.getLogger("uvicorn").handlers)
    if selected_handlers:
        application_logger.handlers = selected_handlers
        application_logger.propagate = False
    else:
        application_logger.propagate = True


def current_request_id() -> str | None:
    return _request_id.get()


def new_request_id() -> str:
    return uuid.uuid4().hex


@contextmanager
def request_context(request_id: str) -> Iterator[None]:
    token = _request_id.set(request_id)
    try:
        yield
    finally:
        _request_id.reset(token)


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    **fields: object,
) -> None:
    payload: dict[str, object] = {"event": event}
    request_id = current_request_id()
    if request_id is not None:
        payload["request_id"] = request_id
    for key, value in fields.items():
        if value is None:
            continue
        payload[key] = round(value, 3) if isinstance(value, float) else value
    logger.log(
        level,
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    )
