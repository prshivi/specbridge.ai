from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.routes import architecture as architecture_route
from app.main import app
from app.models.architecture import ArchitectureRecommendationResult
from app.tests.test_architecture_recommendations import build_architecture

client = TestClient(app)


class StubArchitectureService:
    def __init__(self) -> None:
        self.force_refresh = False

    def recommend(
        self,
        document_id: UUID,
        *,
        force_refresh: bool = False,
    ) -> ArchitectureRecommendationResult:
        self.force_refresh = force_refresh
        architecture = build_architecture(document_id)
        return ArchitectureRecommendationResult(
            document_id=document_id,
            architecture=architecture,
            total_recommendations=13,
            inferred_recommendations=13,
            unresolved_decisions=1,
            cached=False,
            model="test-model",
            prompt_version="architecture-recommendations-v1",
            analyzed_at=datetime.now(UTC),
        )


def test_get_architecture_returns_rationale_and_mermaid(monkeypatch) -> None:
    document_id = uuid4()
    service = StubArchitectureService()
    monkeypatch.setattr(
        architecture_route,
        "get_architecture_service",
        lambda: service,
    )

    response = client.get(
        f"/architecture/{document_id}?force_refresh=true"
    )

    assert response.status_code == 200
    body = response.json()
    architecture = body["architecture"]
    assert architecture["style"]["style"] == "modular_monolith"
    assert architecture["style"]["why"]
    assert architecture["architecture_diagram"]["mermaid"].startswith("flowchart")
    assert architecture["sequence_diagrams"][0]["mermaid"].startswith(
        "sequenceDiagram"
    )
    assert architecture["unresolved_decisions"][0]["clarification_question"]
    assert service.force_refresh is True
