import logging

import pytest

from llm.deepseek_api import DeepSeekAPIError, DeepSeekNetworkError
from core.reliability import RetryPolicy, call_with_retry


def test_retryable_model_request_reuses_request_id_and_increases_attempt(caplog):
    attempts = 0
    delays = []

    def action():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise DeepSeekAPIError(503, "temporary")
        return "ok"

    with caplog.at_level(logging.INFO, logger="study_task.reliability"):
        result = call_with_retry(
            action,
            operation="model_request",
            policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.5),
            sleeper=delays.append,
            request_id="req-fixed",
        )

    assert result == "ok"
    assert attempts == 3
    assert delays == [0.5, 1.0]
    messages = [record.getMessage() for record in caplog.records]
    assert all("request_id=req-fixed" in message for message in messages)
    assert any("attempt=1 status=retrying" in message for message in messages)
    assert any("attempt=2 status=retrying" in message for message in messages)
    assert any("attempt=3 status=succeeded" in message for message in messages)


@pytest.mark.parametrize(
    "error",
    [DeepSeekAPIError(401, "bad key"), ValueError("bad schema")],
)
def test_permanent_or_protocol_error_is_not_retried(error):
    attempts = 0

    def action():
        nonlocal attempts
        attempts += 1
        raise error

    with pytest.raises(type(error)):
        call_with_retry(
            action,
            operation="model_request",
            policy=RetryPolicy(max_attempts=3),
            sleeper=lambda _: None,
        )

    assert attempts == 1


def test_non_idempotent_write_is_not_retried_on_network_error():
    attempts = 0

    def action():
        nonlocal attempts
        attempts += 1
        raise DeepSeekNetworkError("connection lost")

    with pytest.raises(DeepSeekNetworkError):
        call_with_retry(
            action,
            operation="non_idempotent_write",
            policy=RetryPolicy(max_attempts=3),
            sleeper=lambda _: None,
        )

    assert attempts == 1


def test_retry_budget_exhaustion_logs_failure_and_raises(caplog):
    attempts = 0

    def action():
        nonlocal attempts
        attempts += 1
        raise DeepSeekAPIError(429, "busy")

    with caplog.at_level(logging.WARNING, logger="study_task.reliability"):
        with pytest.raises(DeepSeekAPIError) as exc_info:
            call_with_retry(
                action,
                operation="model_request",
                policy=RetryPolicy(max_attempts=2),
                sleeper=lambda _: None,
                request_id="req-final",
            )

    assert exc_info.value.status_code == 429
    assert attempts == 2
    assert any(
        "request_id=req-final" in record.getMessage()
        and "attempt=2 status=failed" in record.getMessage()
        for record in caplog.records
    )
