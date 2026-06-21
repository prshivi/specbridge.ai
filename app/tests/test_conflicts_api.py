from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.routes import conflicts as conflicts_route
from app.main import app
from app.tests.test_framework_conflict_detection import (
    StubConflictProvider,
    build_framework_conflict_output,
    build_framework_conflict_service,
)

client = TestClient(app)


def test_framework_conflict_routes(tmp_path, monkeypatch) -> None:
    document_id = uuid4()
    service = build_framework_conflict_service(
        tmp_path,
        document_id,
        StubConflictProvider(build_framework_conflict_output(document_id)),
    )
    monkeypatch.setattr(
        conflicts_route,
        "get_framework_conflict_service",
        lambda: service,
    )

    run_response = client.post(f"/agents/conflicts/{document_id}")
    list_response = client.get(f"/conflicts/{document_id}")
    detail_response = client.get(f"/conflicts/{document_id}/CON-001")

    assert run_response.status_code == 200
    assert run_response.json()["conflicts"][0]["severity"] == "critical"
    assert list_response.status_code == 200
    assert len(list_response.json()["conflicts"]) == 1
    assert detail_response.status_code == 200
    assert detail_response.json()["recommended_stakeholder"] == "product"


def test_framework_conflict_get_requires_prior_analysis(
    tmp_path,
    monkeypatch,
) -> None:
    document_id = uuid4()
    service = build_framework_conflict_service(
        tmp_path,
        document_id,
        StubConflictProvider(build_framework_conflict_output(document_id)),
    )
    monkeypatch.setattr(
        conflicts_route,
        "get_framework_conflict_service",
        lambda: service,
    )

    response = client.get(f"/conflicts/{document_id}")

    assert response.status_code == 404
