from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.core.config import Settings
from app.core.exceptions import AmbiguityDetectionError
from app.models.ambiguity import (
    AmbiguityAnalysis,
    AmbiguityIssue,
    AmbiguityType,
    IssueSeverity,
    RequirementAmbiguityAssessment,
)
from app.models.requirements import RequirementIntelligenceResult
from app.models.understanding import SpecificationUnderstandingResult
from app.services.ambiguity import AmbiguityDetectionService
from app.services.ambiguity_store import AmbiguityDetectionStore
from app.tests.test_requirement_intelligence import (
    StubChunkService,
    build_chunks,
    build_requirement_result,
)
from app.tests.test_understanding_agent import build_understanding


class StubRequirementService:
    def __init__(self, document_id: UUID) -> None:
        self.document_id = document_id
        self.calls = 0

    def get_requirements(self, document_id: UUID) -> RequirementIntelligenceResult:
        self.calls += 1
        return RequirementIntelligenceResult(
            document_id=document_id,
            requirements=build_requirement_result(document_id).requirements,
            cached=True,
            model="requirements-model",
            prompt_version="requirement-intelligence-v1",
            analyzed_at=datetime.now(UTC),
        )


class StubUnderstandingService:
    def understand(self, document_id: UUID) -> SpecificationUnderstandingResult:
        return SpecificationUnderstandingResult(
            document_id=document_id,
            understanding=build_understanding(),
            cached=True,
            model="understanding-model",
            prompt_version="specification-understanding-v1",
            analyzed_at=datetime.now(UTC),
        )


class StubAmbiguityProvider:
    def __init__(self, result: AmbiguityAnalysis) -> None:
        self.result = result
        self.calls = 0
        self.context = ""

    def analyze(self, context: str) -> AmbiguityAnalysis:
        self.calls += 1
        self.context = context
        return self.result


def build_ambiguity_analysis(document_id: UUID) -> AmbiguityAnalysis:
    return AmbiguityAnalysis(
        assessments=[
            RequirementAmbiguityAssessment(
                requirement_id="FR-001",
                source_chunk=f"{document_id}:1",
                issues=[
                    AmbiguityIssue(
                        issue_id="AMB-001",
                        requirement_id="FR-001",
                        source_chunk=f"{document_id}:1",
                        issue_type=AmbiguityType.MISSING_VALIDATION,
                        severity=IssueSeverity.HIGH,
                        confidence=0.94,
                        reason=(
                            "The requirement asks for email validation but does not "
                            "define the accepted format or failure behavior."
                        ),
                        clarification_question=(
                            "Which email validation rules and failure messages are required?"
                        ),
                        recommended_stakeholder="Product Owner",
                    )
                ],
            ),
            RequirementAmbiguityAssessment(
                requirement_id="PERM-001",
                source_chunk=f"{document_id}:2",
                issues=[],
            ),
        ]
    )


def build_service(
    tmp_path: Path,
    document_id: UUID,
    analysis: AmbiguityAnalysis,
) -> tuple[AmbiguityDetectionService, StubAmbiguityProvider]:
    settings = Settings(
        understanding_cache_db=tmp_path / "specbridge.db",
        openai_ambiguity_model="test-ambiguity-model",
    )
    provider = StubAmbiguityProvider(analysis)
    service = AmbiguityDetectionService(
        settings,
        chunk_service=StubChunkService(build_chunks(document_id)),
        understanding_service=StubUnderstandingService(),
        requirement_service=StubRequirementService(document_id),
        store=AmbiguityDetectionStore(settings.understanding_cache_db),
        provider=provider,
    )
    return service, provider


def test_ambiguity_agent_analyzes_every_requirement_and_caches(
    tmp_path: Path,
) -> None:
    document_id = uuid4()
    service, provider = build_service(
        tmp_path,
        document_id,
        build_ambiguity_analysis(document_id),
    )

    first = service.detect(document_id)
    second = service.detect(document_id)

    assert first.cached is False
    assert second.cached is True
    assert first.total_requirements == 2
    assert first.total_issues == 1
    assert provider.calls == 1
    assert "TOTAL_REQUIREMENTS: 2" in provider.context
    assert f"SOURCE_CHUNK: {document_id}:1" in provider.context
    assert first.assessments[0].issues[0].clarification_question.endswith("?")
    assert first.assessments[1].issues == []


def test_ambiguity_agent_rejects_missing_requirement_assessment(
    tmp_path: Path,
) -> None:
    document_id = uuid4()
    analysis = build_ambiguity_analysis(document_id)
    analysis.assessments.pop()
    service, _ = build_service(tmp_path, document_id, analysis)

    with pytest.raises(AmbiguityDetectionError, match="every requirement"):
        service.detect(document_id)


def test_ambiguity_agent_rejects_mismatched_source_chunk(tmp_path: Path) -> None:
    document_id = uuid4()
    analysis = build_ambiguity_analysis(document_id)
    analysis.assessments[0].issues[0].source_chunk = f"{document_id}:2"
    service, _ = build_service(tmp_path, document_id, analysis)

    with pytest.raises(AmbiguityDetectionError, match="valid source chunk"):
        service.detect(document_id)


def test_all_requested_ambiguity_types_are_supported() -> None:
    assert set(AmbiguityType) == {
        AmbiguityType.VAGUE_LANGUAGE,
        AmbiguityType.MISSING_ACTOR,
        AmbiguityType.MISSING_VALIDATION,
        AmbiguityType.UNDEFINED_BUSINESS_RULE,
        AmbiguityType.MISSING_EDGE_CASE,
        AmbiguityType.MISSING_ERROR_HANDLING,
        AmbiguityType.UNDEFINED_INTEGRATION,
    }

