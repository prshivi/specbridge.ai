from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.routes import spec_health as spec_health_route
from app.main import app
from app.tests.test_spec_health import build_spec_health_service

client = TestClient(app)


def test_spec_health_endpoint(monkeypatch) -> None:
    document_id = uuid4()
    monkeypatch.setattr(
        spec_health_route,
        "get_spec_health_service",
        lambda: build_spec_health_service(document_id),
    )

    response = client.get(f"/spec-health/{document_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == str(document_id)
    assert len(body["metrics"]) == 8
    assert body["overall_health"]["label"] == "Overall Health"
    assert body["next_actions"]
