from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.core.config import Settings
from app.core.exceptions import RequirementIntelligenceError
from app.models.document import ChunkType, DocumentChunk
from app.models.requirements import (
    Requirement,
    RequirementCategory,
    RequirementIntelligence,
    RequirementPriority,
)
from app.models.understanding import SpecificationUnderstandingResult
from app.services.requirements import RequirementIntelligenceService
from app.services.requirements_store import RequirementIntelligenceStore
from app.tests.test_understanding_agent import StubChunkService, build_understanding


class StubUnderstandingService:
    def __init__(self, document_id: UUID) -> None:
        self.document_id = document_id
        self.calls = 0

    def understand(self, document_id: UUID) -> SpecificationUnderstandingResult:
        self.calls += 1
        return SpecificationUnderstandingResult(
            document_id=document_id,
            understanding=build_understanding(),
            cached=True,
            model="understanding-model",
            prompt_version="specification-understanding-v1",
            analyzed_at=datetime.now(UTC),
        )


class StubRequirementProvider:
    def __init__(self, result: RequirementIntelligence) -> None:
        self.result = result
        self.calls = 0
        self.context = ""

    def analyze(self, context: str) -> RequirementIntelligence:
        self.calls += 1
        self.context = context
        return self.result


def build_chunks(document_id: UUID) -> list[DocumentChunk]:
    return [
        DocumentChunk(
            id=f"{document_id}:1",
            document_id=document_id,
            text="The platform must validate the customer's email address.",
            page=1,
            heading="Functional Requirements",
            section="1.1",
            chunk_type=ChunkType.REQUIREMENT,
            chunk_number=1,
        ),
        DocumentChunk(
            id=f"{document_id}:2",
            document_id=document_id,
            text="Only administrators may deactivate an account.",
            page=2,
            heading="Permissions",
            section="1.2",
            chunk_type=ChunkType.REQUIREMENT,
            chunk_number=2,
        ),
    ]


def build_requirement_result(document_id: UUID) -> RequirementIntelligence:
    return RequirementIntelligence(
        requirements=[
            Requirement(
                requirement_id="FR-001",
                title="Validate email",
                description="The platform must validate the customer's email address.",
                priority=RequirementPriority.HIGH,
                confidence=0.98,
                source_chunk=f"{document_id}:1",
                category=RequirementCategory.FUNCTIONAL,
            ),
            Requirement(
                requirement_id="PERM-001",
                title="Restrict deactivation",
                description="Only administrators may deactivate an account.",
                priority=RequirementPriority.HIGH,
                confidence=0.95,
                source_chunk=f"{document_id}:2",
                category=RequirementCategory.PERMISSION,
            ),
        ]
    )


def test_requirement_agent_uses_understanding_chunks_and_cache(tmp_path: Path) -> None:
    document_id = uuid4()
    chunks = build_chunks(document_id)
    provider = StubRequirementProvider(build_requirement_result(document_id))
    understanding_service = StubUnderstandingService(document_id)
    settings = Settings(
        understanding_cache_db=tmp_path / "specbridge.db",
        openai_requirements_model="test-requirements-model",
    )
    service = RequirementIntelligenceService(
        settings,
        chunk_service=StubChunkService(chunks),
        understanding_service=understanding_service,
        store=RequirementIntelligenceStore(settings.understanding_cache_db),
        provider=provider,
    )

    first = service.get_requirements(document_id)
    second = service.get_requirements(document_id)

    assert first.cached is False
    assert second.cached is True
    assert provider.calls == 1
    assert understanding_service.calls == 2
    assert "SPECIFICATION_UNDERSTANDING:" in provider.context
    assert f"SOURCE_CHUNK {document_id}:1" in provider.context
    assert first.requirements[0].confidence == 0.98
    assert first.requirements[0].category is RequirementCategory.FUNCTIONAL


def test_requirement_agent_rejects_unknown_source_chunk(tmp_path: Path) -> None:
    document_id = uuid4()
    chunks = build_chunks(document_id)
    invalid = build_requirement_result(document_id)
    invalid.requirements[0].source_chunk = "unknown:99"
    settings = Settings(understanding_cache_db=tmp_path / "specbridge.db")
    service = RequirementIntelligenceService(
        settings,
        chunk_service=StubChunkService(chunks),
        understanding_service=StubUnderstandingService(document_id),
        provider=StubRequirementProvider(invalid),
    )

    with pytest.raises(RequirementIntelligenceError, match="unknown source chunks"):
        service.get_requirements(document_id)


def test_requirement_agent_rejects_duplicate_ids(tmp_path: Path) -> None:
    document_id = uuid4()
    result = build_requirement_result(document_id)
    result.requirements[1].requirement_id = "FR-001"
    settings = Settings(understanding_cache_db=tmp_path / "specbridge.db")
    service = RequirementIntelligenceService(
        settings,
        chunk_service=StubChunkService(build_chunks(document_id)),
        understanding_service=StubUnderstandingService(document_id),
        provider=StubRequirementProvider(result),
    )

    with pytest.raises(RequirementIntelligenceError, match="must be unique"):
        service.get_requirements(document_id)


def test_all_requested_requirement_categories_are_supported() -> None:
    assert set(RequirementCategory) == {
        RequirementCategory.FUNCTIONAL,
        RequirementCategory.NON_FUNCTIONAL,
        RequirementCategory.BUSINESS_RULE,
        RequirementCategory.DEPENDENCY,
        RequirementCategory.VALIDATION_RULE,
        RequirementCategory.SECURITY,
        RequirementCategory.PERMISSION,
        RequirementCategory.NOTIFICATION,
        RequirementCategory.AUDIT,
    }

