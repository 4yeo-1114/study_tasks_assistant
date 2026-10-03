from dataclasses import dataclass
import logging
from time import perf_counter
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from deepseek_tools import ToolCallProposal
from hybrid_retrieval import HybridRetriever, RetrievalFilters
from readonly_tools import ToolArgumentsError, ToolExecutionResult, ToolNotAllowedError
from observability import log_event


logger = logging.getLogger("study_task.knowledge")


SEARCH_KNOWLEDGE_TOOL: dict[str, object] = {
    "type": "function",
    "function": {
        "name": "search_knowledge",
        "description": "从当前用户的资料库检索与问题相关的资料；只读，不修改数据。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "要检索的问题或关键词",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                    "default": 3,
                    "description": "最多返回的资料分块数量",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}


class SearchKnowledgeArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    limit: int = Field(default=3, strict=True, ge=1, le=5)

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query 不能为空")
        return value.strip()


@dataclass
class KnowledgeToolExecutor:
    retriever: HybridRetriever
    max_calls: int = 2

    def __post_init__(self) -> None:
        if self.max_calls < 1:
            raise ValueError("max_calls 必须大于 0")
        self._call_count = 0
        self._cache: dict[
            tuple[int, str, int],
            tuple[list[dict[str, object]], int],
        ] = {}

    def execute(self, call: ToolCallProposal, *, owner_id: int) -> ToolExecutionResult:
        if call.name != "search_knowledge":
            raise ToolNotAllowedError(f"工具 {call.name} 不在知识检索白名单中")
        if not isinstance(owner_id, int) or isinstance(owner_id, bool) or owner_id < 1:
            raise ValueError("可信 owner_id 必须是正整数")
        if self._call_count >= self.max_calls:
            raise ValueError("知识检索次数已达到上限")
        try:
            #校验agent返回的参数
            arguments = SearchKnowledgeArguments.model_validate(call.arguments)
        except ValidationError as exc:
            raise ToolArgumentsError("工具 search_knowledge 参数校验失败") from exc

        self._call_count += 1
        #幂等键
        cache_key = (owner_id, arguments.query, arguments.limit)
        started = perf_counter()
        cached = self._cache.get(cache_key)
        cache_hit = cached is not None
        if cached is None:
            try:
                results = self.retriever.search(
                    arguments.query,
                    limit=arguments.limit,
                    filters=RetrievalFilters(owner_id=owner_id),
                )
            except Exception as exc:
                log_event(
                    logger,
                    "knowledge_retrieval_failed",
                    level=logging.WARNING,
                    tool_call_id=call.call_id,
                    cache_hit=False,
                    duration_ms=(perf_counter() - started) * 1000,
                    error_type=type(exc).__name__,
                )
                raise
            candidate_count = len(results)
            output = self._serialize(results)
            self._cache[cache_key] = (output, candidate_count)
        else:
            output, candidate_count = cached
        log_event(
            logger,
            "knowledge_retrieval_completed",
            tool_call_id=call.call_id,
            cache_hit=cache_hit,
            candidate_count=candidate_count,
            duration_ms=(perf_counter() - started) * 1000,
        )
        #返回工具执行结果 这里的ToolExecutionResult也适用与其他工具返回结果
        return ToolExecutionResult(call.call_id, call.name, output)

    @staticmethod
    def _serialize(results: list[Any]) -> list[dict[str, object]]:
        if not results:
            return [{"found": False, "message": "没有找到与问题直接相关的资料。"}]
        output = []
        for item in results:
            chunk = getattr(item, "chunk", None)
            if chunk is None:
                raise TypeError("检索结果必须包含 chunk")
            output.append(
                {
                    "found": True,
                    "source": chunk.source,
                    "chunk_id": chunk.chunk_id,
                    "text": chunk.text,
                    "score": getattr(item, "fused_score", getattr(item, "score", None)),
                }
            )
        return output
