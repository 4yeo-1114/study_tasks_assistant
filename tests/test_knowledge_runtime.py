import pytest

from storage.database import Database
from knowledge.knowledge_runtime import (
    KnowledgeRuntime,
    KnowledgeRuntimeConfig,
    KnowledgeRuntimeError,
    build_production_knowledge_factory,
)


class FakeModel:
    model_name = "fake-model"

    def __init__(self, dimension=3):
        self.dimension = dimension
        self.calls = []

    def encode(self, text):
        self.calls.append(text)
        return [0.1] * self.dimension


def test_runtime_shares_retriever_but_returns_fresh_request_executors():
    database = Database("sqlite+pysqlite:///:memory:")
    model = FakeModel()
    runtime = KnowledgeRuntime(
        database.sessions,
        KnowledgeRuntimeConfig("fake-model", 3),
        embedding_model_factory=lambda: model,
    )

    first = runtime.executor_factory()
    second = runtime.executor_factory()

    assert first is not second
    assert first.retriever is second.retriever
    assert model.calls == ["向量维度检查"]
    database.dispose()


def test_runtime_shares_one_document_service_with_the_retriever_dependencies():
    database = Database("sqlite+pysqlite:///:memory:")
    model = FakeModel()
    factory_calls = []

    def model_factory():
        factory_calls.append(1)
        return model

    runtime = KnowledgeRuntime(
        database.sessions,
        KnowledgeRuntimeConfig("fake-model", 3),
        embedding_model_factory=model_factory,
    )

    service = runtime.document_service()
    runtime.executor_factory()

    assert runtime.document_service() is service
    assert factory_calls == [1]
    assert model.calls == ["向量维度检查"]
    database.dispose()


def test_runtime_rejects_embedding_dimension_mismatch():
    database = Database("sqlite+pysqlite:///:memory:")
    runtime = KnowledgeRuntime(
        database.sessions,
        KnowledgeRuntimeConfig("fake-model", 512),
        embedding_model_factory=lambda: FakeModel(dimension=3),
    )

    with pytest.raises(KnowledgeRuntimeError, match="维度"):
        runtime.executor_factory()
    database.dispose()


def test_production_factory_requires_postgresql_when_enabled():
    database = Database("sqlite+pysqlite:///:memory:")

    with pytest.raises(KnowledgeRuntimeError, match="PostgreSQL"):
        build_production_knowledge_factory(database)
    database.dispose()
