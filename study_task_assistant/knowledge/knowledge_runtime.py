import os
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Any

from knowledge.embedding_retrieval import EmbeddingModel, FastEmbedEmbeddingModel
from knowledge.document_service import DocumentService
from knowledge.hybrid_retrieval import HybridRetriever
from knowledge.keyword_retrieval import PgKeywordRetriever
from agent.knowledge_tools import KnowledgeToolExecutor
from storage.pgvector_store import PgVectorConfig, PgVectorRetriever, PgVectorStore


class KnowledgeRuntimeError(RuntimeError):
    """Raised when production knowledge retrieval cannot be initialized."""


@dataclass(frozen=True)
class KnowledgeRuntimeConfig:
    model_name: str = "BAAI/bge-small-zh-v1.5"
    dimension: int = 512
    threads: int = 1
    cache_dir: str | None = None
    max_tool_calls: int = 2

    def __post_init__(self) -> None:
        if not self.model_name.strip():
            raise ValueError("EMBEDDING_MODEL 不能为空")
        if self.dimension < 1:
            raise ValueError("EMBEDDING_DIMENSION 必须大于 0")
        if self.threads < 1:
            raise ValueError("EMBEDDING_THREADS 必须大于 0")
        if self.max_tool_calls < 1:
            raise ValueError("KNOWLEDGE_TOOL_MAX_CALLS 必须大于 0")

    @classmethod
    def from_env(cls) -> "KnowledgeRuntimeConfig":
        return cls(
            model_name=os.environ.get(
                "EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"
            ),
            dimension=int(os.environ.get("EMBEDDING_DIMENSION", "512")),
            threads=int(os.environ.get("EMBEDDING_THREADS", "1")),
            cache_dir=os.environ.get("EMBEDDING_CACHE_DIR") or None,
            max_tool_calls=int(os.environ.get("KNOWLEDGE_TOOL_MAX_CALLS", "2")),
        )


class KnowledgeRuntime:
    """Own shared retrieval dependencies and create request-scoped executors."""

    def __init__(
        self,
        sessions: Any,
        config: KnowledgeRuntimeConfig,
        *,
        embedding_model_factory: Callable[[], EmbeddingModel] | None = None,
    ) -> None:
        self._sessions = sessions
        self._config = config
        self._embedding_model_factory = embedding_model_factory or (
            lambda: FastEmbedEmbeddingModel(
                model_name=config.model_name,
                threads=config.threads,
                cache_dir=config.cache_dir,
            )
        )
        self._retriever: HybridRetriever | None = None
        #文档生命周期 切块 embedding 向量入库的应用服务
        self._document_service: DocumentService | None = None
        self._lock = Lock()

    #执行器工厂
    def executor_factory(self) -> KnowledgeToolExecutor:
        return KnowledgeToolExecutor(
            self._get_retriever(),
            max_calls=self._config.max_tool_calls,
        )

    def _get_retriever(self) -> HybridRetriever:
        self._ensure_initialized()
        assert self._retriever is not None
        return self._retriever

    def document_service(self) -> DocumentService:
        self._ensure_initialized()
        assert self._document_service is not None
        return self._document_service
    #初始化 向量数据库服务 检索器 以及文档服务
    def _ensure_initialized(self) -> None:
        if self._retriever is not None and self._document_service is not None:
            return
        with self._lock:
            if self._retriever is None:
                model = self._embedding_model_factory()
                actual_model = getattr(model, "model_name", None)
                if actual_model != self._config.model_name:
                    raise KnowledgeRuntimeError(
                        "embedding 模型与运行时配置不一致: "
                        f"expected={self._config.model_name}, actual={actual_model}"
                    )
                dimension = len(tuple(model.encode("向量维度检查")))
                if dimension != self._config.dimension:
                    raise KnowledgeRuntimeError(
                        "embedding 向量维度与数据库配置不一致: "
                        f"expected={self._config.dimension}, actual={dimension}"
                    )
                store = PgVectorStore(
                    PgVectorConfig(self._config.model_name, self._config.dimension)
                )
                self._retriever = HybridRetriever(
                    PgKeywordRetriever(self._sessions),
                    PgVectorRetriever(self._sessions, model, store),
                )
                self._document_service = DocumentService(
                    self._sessions,
                    store,
                    model,
                )


def rag_enabled_from_env() -> bool:
    value = os.environ.get("AGENT_RAG_ENABLED", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def build_production_knowledge_factory(
    database: Any,
    *,
    config: KnowledgeRuntimeConfig | None = None,
    embedding_model_factory: Callable[[], EmbeddingModel] | None = None,
) -> Callable[[], KnowledgeToolExecutor]:
    runtime = build_production_runtime(
        database,
        config=config,
        embedding_model_factory=embedding_model_factory,
    )
    return runtime.executor_factory


def build_production_runtime(
    database: Any,
    *,
    config: KnowledgeRuntimeConfig | None = None,
    embedding_model_factory: Callable[[], EmbeddingModel] | None = None,
) -> KnowledgeRuntime:
    if database.engine.dialect.name != "postgresql":
        raise KnowledgeRuntimeError("生产知识检索需要 PostgreSQL + pgvector")
    return KnowledgeRuntime(
        database.sessions,
        config or KnowledgeRuntimeConfig.from_env(),
        embedding_model_factory=embedding_model_factory,
    )
