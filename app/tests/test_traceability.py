import csv
import io
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.core.config import Settings
from app.models.ambiguity import AmbiguityDetectionResult
from app.models.architecture import ArchitectureRecommendationResult
from app.models.assumptions import AssumptionLedgerResult
from app.models.conflicts import (
    ConflictDetectionResult,
    ConflictEvidence,
    ConflictSeverity,
    RequirementConflict,
)
from app.models.engineering import EngineeringTranslationResult
from app.models.requirements import RequirementIntelligenceResult
from app.services.traceability import CSV_COLUMNS, TraceabilityService
from app.tests.test_ambiguity_detection import build_ambiguity_analysis
from app.tests.test_architecture_recommendations import build_architecture
from app.tests.test_assumption_ledger import build_ledger
from app.tests.test_engineering_translator import build_translation
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


class StubTranslatorService:
    def translate(self, document_id: UUID) -> EngineeringTranslationResult:
        return EngineeringTranslationResult(
            document_id=document_id,
            translation=build_translation(document_id),
            total_artifacts=14,
            inferred_artifacts=8,
            blocked_outputs=1,
            cached=True,
            model="translator-model",
            prompt_version="business-to-engineering-v1",
            analyzed_at=datetime.now(UTC),
        )


class StubAssumptionService:
    def get_ledger(self, document_id: UUID) -> AssumptionLedgerResult:
        ledger = build_ledger(document_id)
        return AssumptionLedgerResult(
            document_id=document_id,
            facts=ledger.facts,
            assumptions=ledger.assumptions,
            total_facts=1,
            total_assumptions=1,
            pending_confirmation=1,
            cached=True,
            model="assumption-model",
            prompt_version="assumption-ledger-v1",
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
        conflict = RequirementConflict(
            conflict_id="CON-001",
            conflict="Email validation and deactivation rules may affect account state.",
            evidence=[
                ConflictEvidence(
                    requirement_id="FR-001",
                    source_chunk=f"{document_id}:1",
                    statement="Validate customer email.",
                ),
                ConflictEvidence(
                    requirement_id="PERM-001",
                    source_chunk=f"{document_id}:2",
                    statement="Only administrators may deactivate accounts.",
                ),
            ],
            severity=ConflictSeverity.MEDIUM,
            recommendation="Confirm the permitted account state transitions.",
            confidence=0.7,
            source_chunks=[f"{document_id}:1", f"{document_id}:2"],
        )
        return ConflictDetectionResult(
            document_id=document_id,
            conflicts=[conflict],
            total_requirements=2,
            total_conflicts=1,
            cached=True,
            model="conflict-model",
            prompt_version="conflict-detection-v1",
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


def build_traceability_service(document_id: UUID) -> TraceabilityService:
    return TraceabilityService(
        Settings(),
        chunk_service=StubChunkService(build_chunks(document_id)),
        requirement_service=StubRequirementService(),
        translator_service=StubTranslatorService(),
        assumption_service=StubAssumptionService(),
        ambiguity_service=StubAmbiguityService(),
        conflict_service=StubConflictService(),
        architecture_service=StubArchitectureService(),
    )


def test_traceability_links_complete_chain_per_requirement() -> None:
    document_id = uuid4()
    matrix = build_traceability_service(document_id).build(document_id)

    assert matrix.total_requirements == 2
    first = next(row for row in matrix.rows if row.requirement_id == "FR-001")
    assert first.business_requirement
    assert first.user_stories[0].artifact_id == "US-001"
    assert any(item.artifact_id == "API-001" for item in first.apis)
    assert first.database_entities[0].artifact_id == "DB-001"
    assert first.backend_tasks[0].artifact_id == "TASK-BE-001"
    assert first.acceptance_criteria[0].artifact_id == "AC-001"
    assert first.assumptions[0].assumption_id == "ASM-001"
    clarification_ids = {item.clarification_id for item in first.clarifications}
    assert {"AMB-001", "BLOCK-001", "DEC-001"}.issubset(clarification_ids)
    risk_ids = {item.risk_id for item in first.risks}
    assert {"AMB-001", "CON-001"}.issubset(risk_ids)
    assert first.source_section.source_chunk == f"{document_id}:1"


def test_traceability_preserves_requirements_without_optional_artifacts() -> None:
    document_id = uuid4()
    matrix = build_traceability_service(document_id).build(document_id)

    permission = next(
        row for row in matrix.rows if row.requirement_id == "PERM-001"
    )
    assert permission.user_stories == []
    assert permission.database_entities == []
    assert permission.source_section.source_chunk == f"{document_id}:2"


def test_traceability_csv_has_expected_columns_and_rows() -> None:
    document_id = uuid4()
    content = build_traceability_service(document_id).export_csv(document_id)
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)

    assert reader.fieldnames == CSV_COLUMNS
    assert len(rows) == 2
    first = next(row for row in rows if row["requirement_id"] == "FR-001")
    assert "US-001" in first["user_stories"]
    assert "API-001" in first["apis"]
    assert "ASM-001" in first["assumptions"]
    assert "AMB-001" in first["clarifications"]
    assert "CON-001" in first["risks"]
    assert first["source_chunk"] == f"{document_id}:1"

