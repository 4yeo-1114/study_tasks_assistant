from pgvector_store import PgVectorConfig, PgVectorStore


class Rows:
    def __iter__(self):
        return iter([])


class Session:
    def __init__(self):
        self.statement = None
        self.params = None

    def execute(self, statement, params):
        self.statement = str(statement)
        self.params = params
        return Rows()


def test_pgvector_search_only_reads_ready_active_document_versions():
    session = Session()
    store = PgVectorStore(PgVectorConfig("test-model", 2))

    store.search(session, owner_id=7, query_vector=[0.1, 0.2])

    assert "JOIN documents" in session.statement
    assert "documents.state = 'ready'" in session.statement
    assert "documents.active_version = document_chunks.document_version" in session.statement
