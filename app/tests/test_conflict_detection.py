from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.core.config import Settings
from app.core.exceptions import ConflictDetectionError
from app.models.conflicts import (
    ConflictAnalysis,
    ConflictEvidence,
    ConflictSeverity,
    RequirementConflict,
)
from app.models.document import ChunkType, DocumentChunk
from app.models.requirements import (
    Requirement,
    RequirementCategory,
    RequirementIntelligenceResult,
    RequirementPriority,
)
from app.models.understanding import SpecificationUnderstandingResult
from app.services.conflict_store import ConflictDetectionStore
from app.services.conflicts import ConflictDetectionService
from app.tests.test_understanding_agent import StubChunkService, build_understanding


def build_conflict_requirements(document_id: UUID) -> list[Requirement]:
    return [
        Requirement(
            requirement_id="BR-001",
            title="Refund window",
            description="Customers may request a refund within 7 days.",
            priority=RequirementPriority.HIGH,
            confidence=0.99,
            source_chunk=f"{document_id}:1",
            category=RequirementCategory.BUSINESS_RULE,
        ),
        Requirement(
            requirement_id="BR-002",
            title="No refunds",
            description="Refunds are not allowed.",
            priority=RequirementPriority.HIGH,
            confidence=0.99,
            source_chunk=f"{document_id}:2",
            category=RequirementCategory.BUSINESS_RULE,
        ),
    ]


def build_conflict_chunks(document_id: UUID) -> list[DocumentChunk]:
    return [
        DocumentChunk(
            id=f"{document_id}:1",
            document_id=document_id,
            text="Customers may request a refund within 7 days.",
            heading="Refund Policy",
            chunk_type=ChunkType.BUSINESS_RULE,
            chunk_number=1,
        ),
        DocumentChunk(
            id=f"{document_id}:2",
            document_id=document_id,
            text="Refunds are not allowed.",
            heading="Refund Policy",
            chunk_type=ChunkType.BUSINESS_RULE,
            chunk_number=2,
        ),
    ]


class StubRequirementService:
    def get_requirements(self, document_id: UUID) -> RequirementIntelligenceResult:
        return RequirementIntelligenceResult(
            document_id=document_id,
            requirements=build_conflict_requirements(document_id),
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


class StubConflictProvider:
    def __init__(self, result: ConflictAnalysis) -> None:
        self.result = result
        self.calls = 0
        self.context = ""

    def analyze(self, context: str) -> ConflictAnalysis:
        self.calls += 1
        self.context = context
        return self.result


def build_conflict_analysis(document_id: UUID) -> ConflictAnalysis:
    return ConflictAnalysis(
        conflicts=[
            RequirementConflict(
                conflict_id="CON-001",
                conflict=(
                    "The refund policy both permits refunds within 7 days and "
                    "prohibits all refunds."
                ),
                evidence=[
                    ConflictEvidence(
                        requirement_id="BR-001",
                        source_chunk=f"{document_id}:1",
                        statement="Customers may request a refund within 7 days.",
                    ),
                    ConflictEvidence(
                        requirement_id="BR-002",
                        source_chunk=f"{document_id}:2",
                        statement="Refunds are not allowed.",
                    ),
                ],
                severity=ConflictSeverity.CRITICAL,
                recommendation=(
                    "Ask the policy owner to define the authoritative refund rule "
                    "and any intended exceptions."
                ),
                confidence=0.99,
                source_chunks=[f"{document_id}:1", f"{document_id}:2"],
            )
        ]
    )


def build_service(
    tmp_path: Path,
    document_id: UUID,
    analysis: ConflictAnalysis,
) -> tuple[ConflictDetectionService, StubConflictProvider]:
    settings = Settings(
        understanding_cache_db=tmp_path / "specbridge.db",
        openai_conflict_model="test-conflict-model",
    )
    provider = StubConflictProvider(analysis)
    service = ConflictDetectionService(
        settings,
        chunk_service=StubChunkService(build_conflict_chunks(document_id)),
        understanding_service=StubUnderstandingService(),
        requirement_service=StubRequirementService(),
        store=ConflictDetectionStore(settings.understanding_cache_db),
        provider=provider,
    )
    return service, provider


def test_conflict_agent_detects_contradiction_and_caches(tmp_path: Path) -> None:
    document_id = uuid4()
    service, provider = build_service(
        tmp_path,
        document_id,
        build_conflict_analysis(document_id),
    )

    first = service.detect(document_id)
    second = service.detect(document_id)

    assert first.cached is False
    assert second.cached is True
    assert first.total_requirements == 2
    assert first.total_conflicts == 1
    assert provider.calls == 1
    assert "Customers may request a refund within 7 days." in provider.context
    assert "Refunds are not allowed." in provider.context
    assert first.conflicts[0].severity is ConflictSeverity.CRITICAL
    assert first.conflicts[0].confidence == 0.99


def test_conflict_agent_accepts_no_conflicts(tmp_path: Path) -> None:
    document_id = uuid4()
    service, _ = build_service(
        tmp_path,
        document_id,
        ConflictAnalysis(conflicts=[]),
    )

    result = service.detect(document_id)

    assert result.total_conflicts == 0
    assert result.conflicts == []


def test_conflict_agent_rejects_single_requirement_evidence(
    tmp_path: Path,
) -> None:
    document_id = uuid4()
    analysis = build_conflict_analysis(document_id)
    analysis.conflicts[0].evidence[1].requirement_id = "BR-001"
    analysis.conflicts[0].evidence[1].source_chunk = f"{document_id}:1"
    analysis.conflicts[0].source_chunks = [f"{document_id}:1", f"{document_id}:2"]
    service, _ = build_service(tmp_path, document_id, analysis)

    with pytest.raises(ConflictDetectionError, match="distinct requirements"):
        service.detect(document_id)


def test_conflict_agent_rejects_unmatched_source_chunks(tmp_path: Path) -> None:
    document_id = uuid4()
    analysis = build_conflict_analysis(document_id)
    analysis.conflicts[0].source_chunks = [
        f"{document_id}:1",
        "unknown:3",
    ]
    service, _ = build_service(tmp_path, document_id, analysis)

    with pytest.raises(ConflictDetectionError, match="exactly match"):
        service.detect(document_id)

