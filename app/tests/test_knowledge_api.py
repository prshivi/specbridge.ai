from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.routes import knowledge as knowledge_route
from app.main import app
from app.tests.test_knowledge_graph import build_knowledge_service

client = TestClient(app)


def test_knowledge_build_get_and_graph_endpoints(tmp_path, monkeypatch) -> None:
    document_id = uuid4()
    service = build_knowledge_service(tmp_path, document_id)
    monkeypatch.setattr(
        knowledge_route,
        "get_knowledge_service",
        lambda: service,
    )

    build_response = client.post(f"/knowledge/build/{document_id}")
    model_response = client.get(f"/knowledge/{document_id}")
    graph_response = client.get(f"/knowledge/graph/{document_id}")

    assert build_response.status_code == 201
    assert build_response.json()["entity_count"] > 0
    assert model_response.status_code == 200
    assert model_response.json()["entities"]
    assert graph_response.status_code == 200
    assert graph_response.json()["node_count"] == len(
        model_response.json()["entities"]
    )


def test_knowledge_get_requires_prior_build(tmp_path, monkeypatch) -> None:
    document_id = uuid4()
    service = build_knowledge_service(tmp_path, document_id)
    monkeypatch.setattr(
        knowledge_route,
        "get_knowledge_service",
        lambda: service,
    )

    response = client.get(f"/knowledge/{document_id}")

    assert response.status_code == 404
    assert "has not been built" in response.json()["detail"]
