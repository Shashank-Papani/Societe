from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_live_does_not_require_dependencies(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    body = response.json()
    assert body["error"] is None
    assert body["data"]["status"] == "ok"
    assert "request_id" in body["meta"]
    assert "X-Request-Id" in response.headers


def test_health_ready_reports_dependency_shape(client: TestClient) -> None:
    response = client.get("/health/ready")
    # May be 200 or 503 depending on whether local compose is up.
    assert response.status_code in {200, 503}
    body = response.json()
    assert body["error"] is None
    assert "dependencies" in body["data"]
    names = {dep["name"] for dep in body["data"]["dependencies"]}
    assert names == {"postgres", "valkey"}
