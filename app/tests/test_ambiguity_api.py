from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.routes import ambiguity as ambiguity_route
from app.main import app
from app.models.ambiguity import AmbiguityDetectionResult
from app.tests.test_ambiguity_detection import build_ambiguity_analysis

client = TestClient(app)


class StubAmbiguityService:
    def __init__(self) -> None:
        self.force_refresh = False

    def detect(
        self,
        document_id: UUID,
        *,
        force_refresh: bool = False,
    ) -> AmbiguityDetectionResult:
        self.force_refresh = force_refresh
        analysis = build_ambiguity_analysis(document_id)
        return AmbiguityDetectionResult(
            document_id=document_id,
            assessments=analysis.assessments,
            total_requirements=2,
            total_issues=1,
            cached=False,
            model="test-model",
            prompt_version="ambiguity-detection-v1",
            analyzed_at=datetime.now(UTC),
        )


def test_get_ambiguities_returns_grounded_issues(monkeypatch) -> None:
    document_id = uuid4()
    service = StubAmbiguityService()
    monkeypatch.setattr(
        ambiguity_route,
        "get_ambiguity_service",
        lambda: service,
    )

    response = client.get(
        f"/ambiguities/{document_id}?force_refresh=true"
    )

    assert response.status_code == 200
    body = response.json()
    issue = body["assessments"][0]["issues"][0]
    assert issue["requirement_id"] == "FR-001"
    assert issue["severity"] == "high"
    assert issue["confidence"] == 0.94
    assert issue["recommended_stakeholder"] == "Product Owner"
    assert body["total_requirements"] == 2
    assert service.force_refresh is True
