from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.routes import engineering as engineering_route
from app.main import app
from app.models.engineering import EngineeringTranslationResult
from app.tests.test_engineering_translator import build_translation

client = TestClient(app)


class StubTranslatorService:
    def __init__(self) -> None:
        self.force_refresh = False

    def translate(
        self,
        document_id: UUID,
        *,
        force_refresh: bool = False,
    ) -> EngineeringTranslationResult:
        self.force_refresh = force_refresh
        translation = build_translation(document_id)
        return EngineeringTranslationResult(
            document_id=document_id,
            translation=translation,
            total_artifacts=14,
            inferred_artifacts=8,
            blocked_outputs=1,
            cached=False,
            model="test-model",
            prompt_version="business-to-engineering-v1",
            analyzed_at=datetime.now(UTC),
        )


def test_get_engineering_translation_returns_traceable_artifacts(
    monkeypatch,
) -> None:
    document_id = uuid4()
    service = StubTranslatorService()
    monkeypatch.setattr(
        engineering_route,
        "get_translator_service",
        lambda: service,
    )

    response = client.get(
        f"/engineering/{document_id}?force_refresh=true"
    )

    assert response.status_code == 200
    body = response.json()
    story = body["translation"]["user_stories"][0]
    assert story["requirement_ids"] == ["FR-001"]
    assert story["inferred"] is False
    event = body["translation"]["event_suggestions"][0]
    assert event["inferred"] is True
    assert event["assumption_ids"] == ["ASM-001"]
    assert body["translation"]["blocked_outputs"][0]["clarification_question"]
    assert service.force_refresh is True
