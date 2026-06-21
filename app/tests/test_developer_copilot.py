import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.exceptions import DeveloperCopilotError
from app.models.architecture import ArchitectureRecommendationResult
from app.models.copilot import CopilotAnswer, CopilotCitation
from app.models.requirements import RequirementIntelligenceResult
from app.services.copilot import DeveloperCopilotService
from app.services.copilot_store import DeveloperCopilotStore
from app.tests.test_architecture_recommendations import build_architecture
from app.tests.test_requirement_intelligence import (
    StubChunkService,
    build_chunks,
    build_requirement_result,
)


class StubRequirementService:
    def get_requirements(self, document_id: UUID) -> RequirementIntelligenceResult:
        return RequirementIntelligenceResult(
            document_id=document_id,
            requirements=build_requirement_result(document_id).requirements,
            cached=True,
            model="requirements-model",
            prompt_version="requirement-intelligence-v1",
            analyzed_at=datetime.now(UTC),
        )


class StubArchitectureService:
    def recommend(self, document_id: UUID) -> ArchitectureRecommendationResult:
        return ArchitectureRecommendationResult(
            document_id=document_id,
            architecture=build_architecture(document_id),
            total_recommendations=13,
            inferred_recommendations=13,
            unresolved_decisions=1,
            cached=True,
            model="architecture-model",
            prompt_version="architecture-recommendations-v1",
            analyzed_at=datetime.now(UTC),
        )


class StubCopilotProvider:
    def __init__(self, answer: CopilotAnswer) -> None:
        self.result = answer
        self.calls = 0
        self.context = ""

    def answer(self, context: str) -> CopilotAnswer:
        self.calls += 1
        self.context = context
        return self.result


def build_service(
    tmp_path: Path,
    document_id: UUID,
    answer: CopilotAnswer,
) -> tuple[DeveloperCopilotService, StubCopilotProvider]:
    settings = Settings(
        understanding_cache_db=tmp_path / "specbridge.db",
        openai_copilot_model="test-copilot-model",
    )
    provider = StubCopilotProvider(answer)
    service = DeveloperCopilotService(
        settings,
        chunk_service=StubChunkService(build_chunks(document_id)),
        requirement_service=StubRequirementService(),
        architecture_service=StubArchitectureService(),
        store=DeveloperCopilotStore(settings.understanding_cache_db),
        provider=provider,
    )
    return service, provider


def test_copilot_returns_cited_grounded_answer_and_stores_history(
    tmp_path: Path,
) -> None:
    document_id = uuid4()
    answer = CopilotAnswer(
        answer=(
            "The platform must validate the customer's email address. "
            "A modular monolith is the stored architecture recommendation."
        ),
        available=True,
        citations=[
            CopilotCitation(
                source_chunk=f"{document_id}:1",
                requirement_ids=["FR-001"],
                architecture_ids=["ARCH-STYLE-001"],
            )
        ],
    )
    service, provider = build_service(tmp_path, document_id, answer)

    response = service.ask(document_id, "How should email validation be organized?")

    assert response.available is True
    assert response.citations[0].source_chunk == f"{document_id}:1"
    assert response.clarification_question is None
    assert provider.calls == 1
    assert '"specification_chunks"' in provider.context
    assert '"requirements_and_business_rules"' in provider.context
    assert '"architecture_recommendations"' in provider.context
    assert "assumption_ledger" not in provider.context
    assert "engineering_translation" not in provider.context
    with sqlite3.connect(tmp_path / "specbridge.db") as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM developer_copilot_interactions"
        ).fetchone()[0]
    assert count == 1


def test_copilot_returns_exact_fallback_and_clarification_question(
    tmp_path: Path,
) -> None:
    document_id = uuid4()
    answer = CopilotAnswer(
        answer="Not enough information.",
        available=False,
        clarification_question=(
            "What latency target must the email validation flow meet?"
        ),
        citations=[],
    )
    service, _ = build_service(tmp_path, document_id, answer)

    response = service.ask(document_id, "What is the required latency?")

    assert response.answer == "Not enough information."
    assert response.available is False
    assert response.clarification_question.endswith("?")
    assert response.citations == []


def test_copilot_rejects_unknown_source_chunk(tmp_path: Path) -> None:
    document_id = uuid4()
    answer = CopilotAnswer(
        answer="The platform validates email.",
        available=True,
        citations=[CopilotCitation(source_chunk="unknown:1")],
    )
    service, _ = build_service(tmp_path, document_id, answer)

    with pytest.raises(DeveloperCopilotError, match="unknown source chunk"):
        service.ask(document_id, "Does the platform validate email?")


def test_copilot_rejects_unknown_architecture_reference(tmp_path: Path) -> None:
    document_id = uuid4()
    answer = CopilotAnswer(
        answer="Use a modular monolith.",
        available=True,
        citations=[
            CopilotCitation(
                source_chunk=f"{document_id}:1",
                architecture_ids=["ARCH-UNKNOWN"],
            )
        ],
    )
    service, _ = build_service(tmp_path, document_id, answer)

    with pytest.raises(
        DeveloperCopilotError,
        match="unknown architecture recommendations",
    ):
        service.ask(document_id, "What architecture is recommended?")


def test_unavailable_answer_requires_exact_phrase() -> None:
    with pytest.raises(ValidationError, match="Not enough information"):
        CopilotAnswer(
            answer="I do not know.",
            available=False,
            clarification_question="What behavior is expected?",
            citations=[],
        )

