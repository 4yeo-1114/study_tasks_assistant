from fastapi.testclient import TestClient

from api import create_app
from database import Database
from document_service import DocumentService
from migration import upgrade_database


class FakeModel:
    model_name = "test-model"

    def encode(self, text):
        return [0.1, 0.2]


class FakeStore:
    def __init__(self):
        self.inserted = []
        self.deleted = []

    def insert_chunk(self, session, *, owner_id, chunk, vector, document_version):
        self.inserted.append((owner_id, chunk.source, chunk.chunk_id, document_version))

    def delete_document_version(self, session, *, owner_id, source, document_version):
        self.deleted.append((owner_id, source, document_version))
        return 1


def make_client(tmp_path):
    url = f"sqlite+pysqlite:///{(tmp_path / 'documents-api.db').as_posix()}"
    upgrade_database(url)
    service_database = Database(url)
    store = FakeStore()
    service = DocumentService(service_database.sessions, store, FakeModel())
    app = create_app(
        url,
        token_secret="test-secret-key-at-least-32-bytes",
        settings_factory=lambda: object(),
        document_service_factory=lambda: service,
    )
    return TestClient(app), service_database, store


def auth_headers(client, username):
    password = "password-123"
    client.post("/auth/register", json={"username": username, "password": password})
    token = client.post(
        "/auth/login",
        data={"username": username, "password": password},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def payload(content="Agent 工具调用使用服务端 owner_id"):
    return {
        "source": "agent.md",
        "content": content,
        "document_version": "v1",
        "chunk_size": 100,
        "overlap": 10,
    }


def test_document_routes_require_authentication(tmp_path):
    client, database, _ = make_client(tmp_path)
    with client:
        assert client.get("/documents").status_code == 401
        assert client.post("/documents", json=payload()).status_code == 401
    database.dispose()


def test_blank_document_content_is_rejected_as_request_validation(tmp_path):
    client, database, _ = make_client(tmp_path)
    with client:
        alice = auth_headers(client, "alice")
        response = client.post(
            "/documents",
            json=payload("   "),
            headers=alice,
        )
    database.dispose()

    assert response.status_code == 422


def test_upload_list_get_and_delete_document(tmp_path):
    client, database, store = make_client(tmp_path)
    with client:
        alice = auth_headers(client, "alice")
        created = client.post("/documents", json=payload(), headers=alice)

        assert created.status_code == 201
        body = created.json()
        assert body["source"] == "agent.md"
        assert body["state"] == "ready"
        assert body["chunks_ingested"] == 1

        listed = client.get("/documents", headers=alice).json()
        assert [item["id"] for item in listed] == [body["id"]]
        assert client.get(f"/documents/{body['id']}", headers=alice).status_code == 200

        deleted = client.delete(f"/documents/{body['id']}", headers=alice)
        assert deleted.status_code == 204
        assert store.deleted[-1] == (1, "agent.md", "v1")
    database.dispose()


def test_upload_text_file_uses_filename_as_source(tmp_path):
    client, database, store = make_client(tmp_path)
    with client:
        alice = auth_headers(client, "alice")
        response = client.post(
            "/documents/file",
            files={"file": ("notes.md", "文件正文：幂等操作会避免重复写入。", "text/markdown")},
            data={"document_version": "v1", "chunk_size": "100", "overlap": "10"},
            headers=alice,
        )

    database.dispose()

    assert response.status_code == 201
    assert response.json()["source"] == "notes.md"
    assert response.json()["chunks_ingested"] == 1
    assert store.inserted[-1][1] == "notes.md"


def test_upload_file_rejects_unsupported_extension(tmp_path):
    client, database, _ = make_client(tmp_path)
    with client:
        alice = auth_headers(client, "alice")
        response = client.post(
            "/documents/file",
            files={"file": ("notes.pdf", "not supported", "application/pdf")},
            data={"document_version": "v1"},
            headers=alice,
        )

    database.dispose()

    assert response.status_code == 415


def test_foreign_document_is_hidden_and_version_conflict_is_409(tmp_path):
    client, database, _ = make_client(tmp_path)
    with client:
        alice = auth_headers(client, "alice")
        bob = auth_headers(client, "bob")
        document_id = client.post(
            "/documents", json=payload("first content"), headers=alice
        ).json()["id"]

        assert client.get(f"/documents/{document_id}", headers=bob).status_code == 404
        assert client.delete(f"/documents/{document_id}", headers=bob).status_code == 404

        conflict = client.post(
            "/documents", json=payload("different content"), headers=alice
        )
        assert conflict.status_code == 409
    database.dispose()
