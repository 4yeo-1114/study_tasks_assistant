import json
import logging

from fastapi.testclient import TestClient

from web.api import create_app
from storage.migration import upgrade_database
from core.observability import configure_application_logging, log_event, request_context


def test_log_event_emits_json_with_bound_request_id(caplog):
    logger = logging.getLogger("study_task.test_observability")

    with caplog.at_level(logging.INFO, logger=logger.name):
        with request_context("req-fixed"):
            log_event(logger, "unit_event", duration_ms=12.3456, count=3)

    payload = json.loads(caplog.records[-1].getMessage())
    assert payload == {
        "event": "unit_event",
        "request_id": "req-fixed",
        "duration_ms": 12.346,
        "count": 3,
    }


def test_application_logging_enables_study_task_info_events():
    application_logger = logging.getLogger("study_task")
    logger = logging.getLogger("study_task.runtime_probe")
    previous_level = application_logger.level
    previous_handlers = application_logger.handlers[:]
    previous_propagate = application_logger.propagate
    handler = logging.NullHandler()
    try:
        application_logger.setLevel(logging.WARNING)
        assert not logger.isEnabledFor(logging.INFO)

        configure_application_logging("INFO", handlers=[handler])

        assert logger.isEnabledFor(logging.INFO)
        assert application_logger.handlers == [handler]
        assert application_logger.propagate is False
    finally:
        application_logger.setLevel(previous_level)
        application_logger.handlers = previous_handlers
        application_logger.propagate = previous_propagate


def test_application_logging_discovers_uvicorn_parent_handler():
    application_logger = logging.getLogger("study_task")
    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_error_logger = logging.getLogger("uvicorn.error")
    previous = (
        application_logger.handlers[:],
        application_logger.propagate,
        uvicorn_logger.handlers[:],
        uvicorn_error_logger.handlers[:],
    )
    handler = logging.NullHandler()
    try:
        uvicorn_logger.handlers = [handler]
        uvicorn_error_logger.handlers = []

        configure_application_logging("INFO")

        assert application_logger.handlers == [handler]
        assert application_logger.propagate is False
    finally:
        application_logger.handlers = previous[0]
        application_logger.propagate = previous[1]
        uvicorn_logger.handlers = previous[2]
        uvicorn_error_logger.handlers = previous[3]


def test_http_middleware_returns_request_id_and_logs_completion(tmp_path, caplog):
    url = f"sqlite+pysqlite:///{(tmp_path / 'observability.db').as_posix()}"
    upgrade_database(url)
    app = create_app(url, token_secret="test-secret-key-at-least-32-bytes")

    with caplog.at_level(logging.INFO, logger="study_task.http"):
        with TestClient(app) as client:
            response = client.get("/openapi.json")

    request_id = response.headers["X-Request-ID"]
    assert len(request_id) == 32
    events = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "study_task.http"
    ]
    completed = next(item for item in events if item["event"] == "http_request_completed")
    assert completed["request_id"] == request_id
    assert completed["method"] == "GET"
    assert completed["path"] == "/openapi.json"
    assert completed["status_code"] == 200
    assert completed["duration_ms"] >= 0
