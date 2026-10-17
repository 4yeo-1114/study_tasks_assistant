from fastapi.testclient import TestClient

from web.api import app


def test_app_route_serves_the_workbench_html():
    response = TestClient(app).get("/app")

    assert response.status_code == 200
    assert "学习任务助手" in response.text
