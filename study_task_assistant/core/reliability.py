import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, TypeVar

from llm.deepseek_api import DeepSeekAPIError, DeepSeekNetworkError


logger = logging.getLogger("study_task.reliability")

#能retry的操作类型
RetryOperation = Literal[
    "model_request",
    "read_tool",
    "idempotent_write",
    "non_idempotent_write",
]
#能安全retry的操作类型
_RETRY_SAFE_OPERATIONS = {
    "model_request",
    "read_tool",
    "idempotent_write",
}
T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    """Decide whether one failed operation may be attempted again."""

    max_attempts: int = 3
    base_delay_seconds: float = 0.25
    max_delay_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts 必须大于 0")
        if self.base_delay_seconds < 0:
            raise ValueError("base_delay_seconds 不能小于 0")
        if self.max_delay_seconds < 0:
            raise ValueError("max_delay_seconds 不能小于 0")

    #判断一个操作是否能retry
    def should_retry(
        self,
        error: Exception,
        *,
        operation: RetryOperation,
        attempt: int,
    ) -> bool:
        #超过重试次数
        if attempt >= self.max_attempts:
            return False
        #操作不安全
        if operation not in _RETRY_SAFE_OPERATIONS:
            return False
        #如果是网络层错误可以重试
        if isinstance(error, DeepSeekNetworkError):
            return True
        return isinstance(error, DeepSeekAPIError) and error.retryable
    #返回退避的时间
    def delay_after(self, attempt: int) -> float:
        return min(
            self.base_delay_seconds * (2 ** (attempt - 1)),
            self.max_delay_seconds,
        )


def call_with_retry(
    action: Callable[[], T],
    *,
    operation: RetryOperation,
    policy: RetryPolicy | None = None,
    sleeper: Callable[[float], object] = time.sleep,
    request_id: str | None = None,
) -> T:
    """Run one logical operation with bounded retries and metadata-only logs."""
    retry_policy = policy or RetryPolicy()
    logical_request_id = request_id or uuid.uuid4().hex

    for attempt in range(1, retry_policy.max_attempts + 1):
        logger.info(
            "retry_request request_id=%s operation=%s attempt=%s status=started",
            logical_request_id,
            operation,
            attempt,
        )
        try:
            result = action()
        except Exception as exc:
            retry = retry_policy.should_retry(
                exc,
                operation=operation,
                attempt=attempt,
            )
            status = "retrying" if retry else "failed"
            #看一下错误有没有http返回码
            http_status = getattr(exc, "status_code", None)
            logger.warning(
                "retry_request request_id=%s operation=%s attempt=%s "
                "status=%s error_type=%s http_status=%s",
                logical_request_id,
                operation,
                attempt,
                status,
                type(exc).__name__,
                http_status,
            )
            if not retry:
                raise
            sleeper(retry_policy.delay_after(attempt))
        else:
            logger.info(
                "retry_request request_id=%s operation=%s attempt=%s "
                "status=succeeded",
                logical_request_id,
                operation,
                attempt,
            )
            return result

    raise RuntimeError("重试循环异常结束")
