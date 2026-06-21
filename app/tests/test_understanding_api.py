from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.routes import understanding as understanding_route
from app.main import app
from app.models.understanding import SpecificationUnderstandingResult
from app.tests.test_understanding_agent import build_understanding

client = TestClient(app)


class StubUnderstandingService:
    def __init__(self, document_id: UUID) -> None:
        self.document_id = document_id
        self.force_refresh = False

    def understand(
        self,
        document_id: UUID,
        *,
        force_refresh: bool = False,
    ) -> SpecificationUnderstandingResult:
        self.document_id = document_id
        self.force_refresh = force_refresh
        return SpecificationUnderstandingResult(
            document_id=document_id,
            understanding=build_understanding(),
            cached=False,
            model="test-model",
            prompt_version="specification-understanding-v1",
            analyzed_at=datetime.now(UTC),
        )


def test_understanding_endpoint_returns_structured_json(monkeypatch) -> None:
    document_id = uuid4()
    service = StubUnderstandingService(document_id)
    monkeypatch.setattr(
        understanding_route,
        "get_understanding_service",
        lambda: service,
    )

    response = client.post(
        f"/documents/{document_id}/understanding?force_refresh=true"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == str(document_id)
    assert body["understanding"]["document_type"] == "Product requirements document"
    assert body["understanding"]["actors"][0]["name"] == "Customer"
    assert service.force_refresh is True
