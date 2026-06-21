from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.core.config import Settings
from app.core.exceptions import AssumptionLedgerError
from app.models.ambiguity import AmbiguityDetectionResult
from app.models.assumptions import AssumptionLedger, AssumptionRecord, FactRecord
from app.models.conflicts import ConflictDetectionResult
from app.models.requirements import RequirementIntelligenceResult
from app.models.understanding import SpecificationUnderstandingResult
from app.services.assumption_store import AssumptionLedgerStore
from app.services.assumptions import AssumptionLedgerService
from app.tests.test_ambiguity_detection import build_ambiguity_analysis
from app.tests.test_conflict_detection import build_conflict_analysis
from app.tests.test_requirement_intelligence import (
    StubChunkService,
    build_chunks,
    build_requirement_result,
)
from app.tests.test_understanding_agent import build_understanding


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


class StubAmbiguityService:
    def detect(self, document_id: UUID) -> AmbiguityDetectionResult:
        analysis = build_ambiguity_analysis(document_id)
        return AmbiguityDetectionResult(
            document_id=document_id,
            assessments=analysis.assessments,
            total_requirements=2,
            total_issues=1,
            cached=True,
            model="ambiguity-model",
            prompt_version="ambiguity-detection-v1",
            analyzed_at=datetime.now(UTC),
        )


class StubConflictService:
    def detect(self, document_id: UUID) -> ConflictDetectionResult:
        analysis = build_conflict_analysis(document_id)
        return ConflictDetectionResult(
            document_id=document_id,
            conflicts=analysis.conflicts,
            total_requirements=2,
            total_conflicts=1,
            cached=True,
            model="conflict-model",
            prompt_version="conflict-detection-v1",
            analyzed_at=datetime.now(UTC),
        )


class StubAssumptionProvider:
    def __init__(self, result: AssumptionLedger) -> None:
        self.result = result
        self.calls = 0
        self.context = ""

    def analyze(self, context: str) -> AssumptionLedger:
        self.calls += 1
        self.context = context
        return self.result


def build_ledger(document_id: UUID) -> AssumptionLedger:
    return AssumptionLedger(
        facts=[
            FactRecord(
                fact_id="FACT-001",
                fact="The platform must validate the customer's email address.",
                affected_outputs=["requirements.FR-001.description"],
                source_chunk=f"{document_id}:1",
            )
        ],
        assumptions=[
            AssumptionRecord(
                assumption_id="ASM-001",
                assumption="Email validation is a high-priority requirement.",
                reason=(
                    "The source requires validation but does not explicitly assign "
                    "a priority."
                ),
                confidence=0.72,
                affected_outputs=["requirements.FR-001.priority"],
                needs_confirmation=True,
                source_chunk=f"{document_id}:1",
            )
        ],
    )


def build_service(
    tmp_path: Path,
    document_id: UUID,
    ledger: AssumptionLedger,
) -> tuple[AssumptionLedgerService, StubAssumptionProvider]:
    settings = Settings(
        understanding_cache_db=tmp_path / "specbridge.db",
        openai_assumption_model="test-assumption-model",
    )
    provider = StubAssumptionProvider(ledger)
    service = AssumptionLedgerService(
        settings,
        chunk_service=StubChunkService(build_chunks(document_id)),
        understanding_service=StubUnderstandingService(),
        requirement_service=StubRequirementService(),
        ambiguity_service=StubAmbiguityService(),
        conflict_service=StubConflictService(),
        store=AssumptionLedgerStore(settings.understanding_cache_db),
        provider=provider,
    )
    return service, provider


def test_assumption_ledger_separates_facts_and_assumptions_and_caches(
    tmp_path: Path,
) -> None:
    document_id = uuid4()
    service, provider = build_service(tmp_path, document_id, build_ledger(document_id))

    first = service.get_ledger(document_id)
    second = service.get_ledger(document_id)

    assert first.cached is False
    assert second.cached is True
    assert first.total_facts == 1
    assert first.total_assumptions == 1
    assert first.pending_confirmation == 1
    assert provider.calls == 1
    assert "requirements.FR-001.description" in provider.context
    assert "requirements.FR-001.priority" in provider.context
    assert first.facts[0].fact_id == "FACT-001"
    assert first.assumptions[0].needs_confirmation is True


def test_assumption_ledger_rejects_unknown_affected_output(tmp_path: Path) -> None:
    document_id = uuid4()
    ledger = build_ledger(document_id)
    ledger.assumptions[0].affected_outputs = ["requirements.FR-999.priority"]
    service, _ = build_service(tmp_path, document_id, ledger)

    with pytest.raises(AssumptionLedgerError, match="unknown affected outputs"):
        service.get_ledger(document_id)


def test_assumption_ledger_rejects_unknown_source_chunk(tmp_path: Path) -> None:
    document_id = uuid4()
    ledger = build_ledger(document_id)
    ledger.facts[0].source_chunk = "unknown:1"
    service, _ = build_service(tmp_path, document_id, ledger)

    with pytest.raises(AssumptionLedgerError, match="valid source chunks"):
        service.get_ledger(document_id)


def test_assumption_ledger_rejects_duplicate_record_ids(tmp_path: Path) -> None:
    document_id = uuid4()
    ledger = build_ledger(document_id)
    ledger.assumptions[0].assumption_id = "FACT-001"
    service, _ = build_service(tmp_path, document_id, ledger)

    with pytest.raises(AssumptionLedgerError, match="must be unique"):
        service.get_ledger(document_id)

