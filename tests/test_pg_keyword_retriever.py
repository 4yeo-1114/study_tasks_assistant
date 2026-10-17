from knowledge.keyword_retrieval import PgKeywordRetriever


class Row:
    def __init__(self, source, chunk_id, content):
        self.source = source
        self.chunk_id = chunk_id
        self.content = content


class Session:
    def __init__(self, rows):
        self.rows = rows
        self.statement = None
        self.params = None

    def execute(self, statement, params):
        self.statement = str(statement)
        self.params = params
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Sessions:
    def __init__(self, rows):
        self.session = Session(rows)

    def __call__(self):
        return self.session


def test_pg_keyword_retriever_scopes_rows_in_sql_before_scoring():
    sessions = Sessions([
        Row("weak.md", 1, "Agent 工具"),
        Row("strong.md", 2, "Agent 工具调用需要校验工具参数"),
    ])
    retriever = PgKeywordRetriever(sessions)

    results = retriever.search(
        "Agent 工具调用参数",
        owner_id=7,
        source="strong.md",
        document_version="v2",
        limit=2,
    )

    assert [item.chunk.source for item in results] == ["strong.md", "weak.md"]
    assert "document_chunks.owner_id = :owner_id" in sessions.session.statement
    assert "documents.state = 'ready'" in sessions.session.statement
    assert "documents.active_version = document_chunks.document_version" in sessions.session.statement
    assert sessions.session.params == {
        "owner_id": 7,
        "source": "strong.md",
        "document_version": "v2",
    }


def test_pg_keyword_retriever_returns_no_match_instead_of_unrelated_chunks():
    retriever = PgKeywordRetriever(Sessions([Row("other.md", 1, "完全无关内容")]))

    assert retriever.search("pgvector", owner_id=1) == []
