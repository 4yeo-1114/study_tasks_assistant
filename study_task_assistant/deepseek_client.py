import logging
import uuid
from collections.abc import Iterator, Sequence

import httpx

from deepseek_api import (
    DeepSeekReply,
    DeepSeekSettings,
    request_chat,
    stream_chat,
)
from model_client import ModelMessage


logger = logging.getLogger("study_task.deepseek")


class DeepSeekClient:
    """Keep shared DeepSeek configuration for normal and streaming calls."""

    def __init__(
        self,
        *,
        settings: DeepSeekSettings,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0")
        self._settings = settings
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def chat(self, messages: Sequence[ModelMessage]) -> DeepSeekReply:
        request_id = self._start_request("chat")
        try:
            reply = request_chat(
                messages,
                settings=self._settings,
                timeout_seconds=self._timeout_seconds,
                transport=self._transport,
            )
        except Exception as exc:
            self._log_failure(request_id, "chat", exc)
            raise

        self._log_success(request_id, "chat")
        return reply

    def stream(self, messages: Sequence[ModelMessage]) -> Iterator[str]:
        request_id = self._start_request("stream")
        try:
            yield from stream_chat(
                messages,
                settings=self._settings,
                timeout_seconds=self._timeout_seconds,
                transport=self._transport,
            )
        except Exception as exc:
            self._log_failure(request_id, "stream", exc)
            raise

        self._log_success(request_id, "stream")

    def _start_request(self, mode: str) -> str:
        request_id = uuid.uuid4().hex
        logger.info(
            "deepseek_request request_id=%s mode=%s model=%s status=started",
            request_id,
            mode,
            self._settings.model,
        )
        return request_id

    @staticmethod
    def _log_success(request_id: str, mode: str) -> None:
        logger.info(
            "deepseek_request request_id=%s mode=%s status=succeeded",
            request_id,
            mode,
        )

    @staticmethod
    def _log_failure(request_id: str, mode: str, exc: Exception) -> None:
        logger.warning(
            "deepseek_request request_id=%s mode=%s status=failed error_type=%s",
            request_id,
            mode,
            type(exc).__name__,
        )
