from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.routes import copilot as copilot_route
from app.main import app
from app.models.copilot import CopilotCitation, DeveloperCopilotResponse

client = TestClient(app)


class StubCopilotService:
    def ask(self, document_id: UUID, question: str) -> DeveloperCopilotResponse:
        return DeveloperCopilotResponse(
            interaction_id="interaction-1",
            document_id=document_id,
            question=question,
            answer="The platform must validate the customer email address.",
            available=True,
            clarification_question=None,
            citations=[
                CopilotCitation(
                    source_chunk=f"{document_id}:1",
                    requirement_ids=["FR-001"],
                )
            ],
            model="test-model",
            prompt_version="developer-copilot-v1",
            answered_at=datetime.now(UTC),
        )


def test_copilot_endpoint_answers_with_source_chunks(monkeypatch) -> None:
    document_id = uuid4()
    monkeypatch.setattr(
        copilot_route,
        "get_copilot_service",
        lambda: StubCopilotService(),
    )

    response = client.post(
        f"/copilot/{document_id}/ask",
        json={"question": "Does the platform validate email?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["citations"][0]["source_chunk"] == f"{document_id}:1"
    assert body["citations"][0]["requirement_ids"] == ["FR-001"]

