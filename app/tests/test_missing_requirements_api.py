from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.routes import missing_requirements as missing_route
from app.main import app
from app.tests.test_missing_requirement_detection import (
    StubMissingProvider,
    build_missing_output,
    build_missing_service,
)

client = TestClient(app)


def test_missing_requirement_routes(tmp_path, monkeypatch) -> None:
    document_id = uuid4()
    service = build_missing_service(
        tmp_path,
        document_id,
        StubMissingProvider(build_missing_output(document_id)),
    )
    monkeypatch.setattr(
        missing_route,
        "get_missing_requirement_service",
        lambda: service,
    )

    run_response = client.post(f"/agents/missing-requirements/{document_id}")
    list_response = client.get(f"/missing-requirements/{document_id}")
    detail_response = client.get(
        f"/missing-requirements/{document_id}/MISS-001"
    )

    assert run_response.status_code == 200
    assert run_response.json()["missing_requirements"][0][
        "gap_type"
    ] == "integration_failure_handling"
    assert list_response.status_code == 200
    assert len(list_response.json()["missing_requirements"]) == 1
    assert detail_response.status_code == 200
    assert detail_response.json()["clarification_question"].endswith("?")


def test_missing_requirement_get_requires_prior_analysis(
    tmp_path,
    monkeypatch,
) -> None:
    document_id = uuid4()
    service = build_missing_service(
        tmp_path,
        document_id,
        StubMissingProvider(build_missing_output(document_id)),
    )
    monkeypatch.setattr(
        missing_route,
        "get_missing_requirement_service",
        lambda: service,
    )

    response = client.get(f"/missing-requirements/{document_id}")

    assert response.status_code == 404
