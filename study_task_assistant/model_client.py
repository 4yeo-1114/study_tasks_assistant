from dataclasses import dataclass
from typing import Literal, Sequence, Union


@dataclass(frozen=True)
class ModelMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class TextResponse:
    text: str


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, object]


ModelOutput = Union[TextResponse, ToolCall]


class ModelTimeoutError(TimeoutError):
    pass


class FakeModelClient:
    """Return a fixed response without contacting a real model service."""

    def __init__(
        self,
        output: ModelOutput,
        *,
        required_latency_seconds: float = 0,
    ) -> None:
        if required_latency_seconds < 0:
            raise ValueError("模拟延迟不能小于 0")
        self._output = output
        self._required_latency_seconds = required_latency_seconds
        self.calls: list[list[ModelMessage]] = []

    def complete(
        self,
        messages: Sequence[ModelMessage],
        *,
        timeout_seconds: float,
    ) -> ModelOutput:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0")

        self.calls.append(list(messages))
        if self._required_latency_seconds > timeout_seconds:
            raise ModelTimeoutError(
                f"模型需要 {self._required_latency_seconds:g} 秒，"
                f"超过 {timeout_seconds:g} 秒超时限制"
            )
        return self._output
