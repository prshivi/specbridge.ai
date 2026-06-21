from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.routes import specification_dna as dna_route
from app.main import app
from app.tests.test_specification_dna_agent import (
    StubDNAProvider,
    build_dna_service,
    build_specification_dna,
)

client = TestClient(app)


def test_specification_dna_endpoint_returns_structured_json(
    tmp_path,
    monkeypatch,
) -> None:
    document_id = uuid4()
    service = build_dna_service(
        tmp_path,
        document_id,
        StubDNAProvider(build_specification_dna(document_id)),
    )
    monkeypatch.setattr(
        dna_route,
        "get_specification_dna_service",
        lambda: service,
    )

    response = client.get(f"/specification-dna/{document_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == str(document_id)
    assert body["specification_dna"]["project_name"]["value"] == "Account Bridge"
    assert body["specification_dna"]["actors"][0]["source_chunk_ids"]
    assert body["specification_dna"]["workflows"][0][
        "source_document_sections"
    ] == ["2.1"]
