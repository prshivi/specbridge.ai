from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.routes import requirements as requirements_route
from app.main import app
from app.tests.test_requirement_extraction_agent import (
    StubRequirementExtractionProvider,
    build_extraction,
    build_extraction_service,
)

client = TestClient(app)


def test_requirement_extraction_routes(tmp_path, monkeypatch) -> None:
    document_id = uuid4()
    service = build_extraction_service(
        tmp_path,
        document_id,
        StubRequirementExtractionProvider(build_extraction(document_id)),
    )
    monkeypatch.setattr(
        requirements_route,
        "get_requirement_extraction_service",
        lambda: service,
    )

    run_response = client.post(f"/agents/requirements/{document_id}")
    list_response = client.get(f"/requirements/{document_id}")
    detail_response = client.get(f"/requirements/{document_id}/FR-001")

    assert run_response.status_code == 200
    assert run_response.json()["requirements"][0]["requirement_id"] == "FR-001"
    assert list_response.status_code == 200
    assert len(list_response.json()["requirements"]) == 2
    assert detail_response.status_code == 200
    assert detail_response.json()["evidence_text"].startswith("The platform")


def test_requirement_routes_return_not_found_before_extraction(
    tmp_path,
    monkeypatch,
) -> None:
    document_id = uuid4()
    service = build_extraction_service(
        tmp_path,
        document_id,
        StubRequirementExtractionProvider(build_extraction(document_id)),
    )
    monkeypatch.setattr(
        requirements_route,
        "get_requirement_extraction_service",
        lambda: service,
    )

    response = client.get(f"/requirements/{document_id}")

    assert response.status_code == 404
