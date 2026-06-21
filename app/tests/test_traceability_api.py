from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.routes import traceability as traceability_route
from app.main import app
from app.tests.test_traceability import build_traceability_service

client = TestClient(app)


def test_traceability_json_endpoint(monkeypatch) -> None:
    document_id = uuid4()
    service = build_traceability_service(document_id)
    monkeypatch.setattr(
        traceability_route,
        "get_traceability_service",
        lambda: service,
    )

    response = client.get(f"/traceability/{document_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["total_requirements"] == 2
    assert body["rows"][0]["source_section"]["source_chunk"]


def test_traceability_csv_download(monkeypatch) -> None:
    document_id = uuid4()
    service = build_traceability_service(document_id)
    monkeypatch.setattr(
        traceability_route,
        "get_traceability_service",
        lambda: service,
    )

    response = client.get(f"/traceability/{document_id}/export.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment;" in response.headers["content-disposition"]
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert b"requirement_id,business_requirement" in response.content

