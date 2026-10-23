from fastapi.testclient import TestClient
from fastapi.exceptions import ResponseValidationError
import pytest
from fitness.service import FitnessService

from storage.migration import upgrade_database
from web.api import create_app


CSV = "workout_date,exercise_name,weight_kg,reps,recorded_on\n2026-10-18,卧推,60,5,\n2026-10-18,卧推,50,8,\n"


def client_for(tmp_path):
    database = tmp_path / "fitness-import.db"
    upgrade_database(f"sqlite+pysqlite:///{database.as_posix()}")
    client = TestClient(create_app(database, token_secret="test-only-secret-key-at-least-32-bytes"))
    client.post("/auth/register", json={"username": "import_user", "password": "test-password-123"})
    token = client.post("/auth/login", data={"username": "import_user", "password": "test-password-123"}).json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def test_csv_preview_validates_without_writing(tmp_path):
    client = client_for(tmp_path)
    preview = client.post("/fitness/import/preview", json={"csv_text": CSV})
    assert preview.status_code == 200
    assert preview.json()["row_count"] == 2
    assert client.get("/fitness/progress").json()["volume_by_exercise"] == {}


def test_csv_commit_is_idempotent(tmp_path):
    client = client_for(tmp_path)
    first = client.post("/fitness/import/commit", json={"csv_text": CSV})
    second = client.post("/fitness/import/commit", json={"csv_text": CSV})
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json() == first.json()
    assert client.get("/fitness/progress").json()["volume_by_exercise"]["卧推"] == 700


def test_csv_commit_validates_the_declared_response_model(tmp_path, monkeypatch):
    client = client_for(tmp_path)

    monkeypatch.setattr(
        FitnessService,
        "commit_import",
        lambda *_: {"row_count": 1, "workout_count": 1, "created": True},
    )

    with pytest.raises(ResponseValidationError):
        client.post("/fitness/import/commit", json={"csv_text": CSV})


def test_csv_preview_rejects_invalid_rows(tmp_path):
    client = client_for(tmp_path)
    response = client.post(
        "/fitness/import/preview",
        json={"csv_text": "workout_date,exercise_name,weight_kg,reps\n2026-02-30,卧推,60,5\n"},
    )
    assert response.status_code == 422


def test_csv_rejects_non_finite_weight_and_ambiguous_date(tmp_path):
    client = client_for(tmp_path)
    for csv_text in (
        "workout_date,exercise_name,weight_kg,reps,recorded_on\n2026-10-18,卧推,inf,5,\n",
        "workout_date,exercise_name,weight_kg,reps,recorded_on\n2026-10-18,卧推,60,5,2026-10-18\n",
    ):
        assert client.post("/fitness/import/preview", json={"csv_text": csv_text}).status_code == 422
