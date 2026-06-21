from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.exceptions import ArchitectureRecommendationError
from app.models.ambiguity import AmbiguityDetectionResult
from app.models.architecture import (
    ArchitectureDecisionGap,
    ArchitectureFlowDiagram,
    ArchitectureRecommendations,
    ArchitectureStyle,
    ArchitectureStyleRecommendation,
    ExternalServiceRecommendation,
    ModuleRecommendation,
    SequenceDiagram,
    ServiceRecommendation,
    TechnologyRecommendation,
)
from app.models.assumptions import AssumptionLedgerResult
from app.models.conflicts import ConflictDetectionResult
from app.models.engineering import EngineeringTranslationResult
from app.models.requirements import RequirementIntelligenceResult
from app.models.understanding import SpecificationUnderstandingResult
from app.services.architecture import ArchitectureRecommendationService
from app.services.architecture_store import ArchitectureRecommendationStore
from app.tests.test_assumption_ledger import build_ledger
from app.tests.test_engineering_translator import build_translation
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
        return AmbiguityDetectionResult(
            document_id=document_id,
            assessments=[],
            total_requirements=0,
            total_issues=0,
            cached=True,
            model="ambiguity-model",
            prompt_version="ambiguity-detection-v1",
            analyzed_at=datetime.now(UTC),
        )


class StubConflictService:
    def detect(self, document_id: UUID) -> ConflictDetectionResult:
        return ConflictDetectionResult(
            document_id=document_id,
            conflicts=[],
            total_requirements=2,
            total_conflicts=0,
            cached=True,
            model="conflict-model",
            prompt_version="conflict-detection-v1",
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


class StubArchitectureProvider:
    def __init__(self, architecture: ArchitectureRecommendations) -> None:
        self.architecture = architecture
        self.calls = 0
        self.context = ""

    def analyze(self, context: str) -> ArchitectureRecommendations:
        self.calls += 1
        self.context = context
        return self.architecture


def recommendation_metadata(
    document_id: UUID,
    recommendation_id: str,
) -> dict[str, object]:
    return {
        "recommendation_id": recommendation_id,
        "name": recommendation_id,
        "recommendation": "Use the simplest architecture supported by current scope.",
        "why": "The requirements describe one cohesive workflow without independent scale.",
        "requirement_ids": ["FR-001"],
        "source_chunks": [f"{document_id}:1"],
        "confidence": 0.76,
        "inferred": True,
        "inference_reason": "Architecture style is not explicitly specified.",
        "assumption_ids": ["ASM-001"],
    }


def diagram_metadata(
    document_id: UUID,
    diagram_id: str,
    title: str,
) -> dict[str, object]:
    return {
        "diagram_id": diagram_id,
        "title": title,
        "why": "Shows the requirement-supported validation workflow.",
        "requirement_ids": ["FR-001"],
        "source_chunks": [f"{document_id}:1"],
        "inferred": True,
        "inference_reason": "Component boundaries are an architecture interpretation.",
        "assumption_ids": ["ASM-001"],
    }


def technology(
    document_id: UUID,
    recommendation_id: str,
    option: str,
) -> TechnologyRecommendation:
    return TechnologyRecommendation(
        **recommendation_metadata(document_id, recommendation_id),
        option=option,
        alternatives=[],
        operational_considerations=["Revisit when scale requirements are known."],
    )


def build_architecture(document_id: UUID) -> ArchitectureRecommendations:
    return ArchitectureRecommendations(
        summary=(
            "Start with a modular monolith and explicit module boundaries; "
            "extract services only when operational triggers emerge."
        ),
        style=ArchitectureStyleRecommendation(
            **recommendation_metadata(document_id, "ARCH-STYLE-001"),
            style=ArchitectureStyle.MODULAR_MONOLITH,
            rejected_styles=[
                ArchitectureStyle.MONOLITH,
                ArchitectureStyle.MICROSERVICES,
            ],
            evolution_trigger=(
                "Extract a service when independent scaling or isolation is required."
            ),
        ),
        modules=[
            ModuleRecommendation(
                **recommendation_metadata(document_id, "MOD-001"),
                responsibilities=["Registration", "Email validation"],
                dependencies=[],
            )
        ],
        services=[
            ServiceRecommendation(
                **recommendation_metadata(document_id, "SVC-001"),
                responsibilities=["Expose registration capability"],
                independently_deployable=False,
                extraction_trigger="Independent scaling or release ownership",
            )
        ],
        database=technology(document_id, "TECH-DB-001", "Relational database"),
        caching=technology(document_id, "TECH-CACHE-001", "No distributed cache initially"),
        messaging=technology(document_id, "TECH-MSG-001", "Synchronous in-process flow"),
        authentication=technology(
            document_id,
            "TECH-AUTH-001",
            "Authentication mechanism remains unresolved",
        ),
        external_services=[
            ExternalServiceRecommendation(
                **recommendation_metadata(document_id, "EXT-001"),
                purpose="Optional email verification delivery",
                selection_criteria=["Supported delivery channels", "Security controls"],
            )
        ],
        deployment=technology(document_id, "TECH-DEPLOY-001", "Single deployable service"),
        architecture_diagram=ArchitectureFlowDiagram(
            **diagram_metadata(document_id, "DIAG-ARCH-001", "Registration Architecture"),
            mermaid=(
                "flowchart LR\n"
                "  Client --> API\n"
                "  API --> RegistrationModule\n"
                "  RegistrationModule --> Database"
            ),
        ),
        sequence_diagrams=[
            SequenceDiagram(
                **diagram_metadata(document_id, "DIAG-SEQ-001", "Validate Registration"),
                mermaid=(
                    "sequenceDiagram\n"
                    "  participant Customer\n"
                    "  participant Registration\n"
                    "  Customer->>Registration: Submit email\n"
                    "  Registration-->>Customer: Validation result"
                ),
            )
        ],
        unresolved_decisions=[
            ArchitectureDecisionGap(
                decision_id="DEC-001",
                topic="Authentication",
                missing_information="No authentication requirements are specified.",
                why_it_matters="It determines identity and access boundaries.",
                clarification_question="Which actors must authenticate, and how?",
                requirement_ids=["FR-001"],
                source_chunks=[f"{document_id}:1"],
            )
        ],
    )


def build_service(
    tmp_path: Path,
    document_id: UUID,
    architecture: ArchitectureRecommendations,
) -> tuple[ArchitectureRecommendationService, StubArchitectureProvider]:
    settings = Settings(
        understanding_cache_db=tmp_path / "specbridge.db",
        openai_architecture_model="test-architecture-model",
    )
    provider = StubArchitectureProvider(architecture)
    service = ArchitectureRecommendationService(
        settings,
        chunk_service=StubChunkService(build_chunks(document_id)),
        understanding_service=StubUnderstandingService(),
        requirement_service=StubRequirementService(),
        ambiguity_service=StubAmbiguityService(),
        conflict_service=StubConflictService(),
        assumption_service=StubAssumptionService(),
        translator_service=StubTranslatorService(),
        store=ArchitectureRecommendationStore(settings.understanding_cache_db),
        provider=provider,
    )
    return service, provider


def test_architecture_agent_returns_recommendations_diagrams_and_cache(
    tmp_path: Path,
) -> None:
    document_id = uuid4()
    service, provider = build_service(
        tmp_path,
        document_id,
        build_architecture(document_id),
    )

    first = service.recommend(document_id)
    second = service.recommend(document_id)

    assert first.cached is False
    assert second.cached is True
    assert provider.calls == 1
    assert first.architecture.style.style is ArchitectureStyle.MODULAR_MONOLITH
    assert first.architecture.modules
    assert first.architecture.services
    assert first.architecture.database.why
    assert first.architecture.architecture_diagram.mermaid.startswith("flowchart")
    assert first.architecture.sequence_diagrams[0].mermaid.startswith(
        "sequenceDiagram"
    )
    assert first.unresolved_decisions == 1
    assert first.inferred_recommendations == first.total_recommendations
    assert '"engineering_translation"' in provider.context


def test_architecture_agent_rejects_unknown_requirement(tmp_path: Path) -> None:
    document_id = uuid4()
    architecture = build_architecture(document_id)
    architecture.modules[0].requirement_ids = ["FR-999"]
    service, _ = build_service(tmp_path, document_id, architecture)

    with pytest.raises(ArchitectureRecommendationError, match="unknown requirements"):
        service.recommend(document_id)


def test_architecture_agent_rejects_unknown_assumption(tmp_path: Path) -> None:
    document_id = uuid4()
    architecture = build_architecture(document_id)
    architecture.database.assumption_ids = ["ASM-999"]
    service, _ = build_service(tmp_path, document_id, architecture)

    with pytest.raises(ArchitectureRecommendationError, match="unknown assumptions"):
        service.recommend(document_id)


def test_architecture_agent_rejects_mismatched_chunks(tmp_path: Path) -> None:
    document_id = uuid4()
    architecture = build_architecture(document_id)
    architecture.deployment.source_chunks = [f"{document_id}:2"]
    service, _ = build_service(tmp_path, document_id, architecture)

    with pytest.raises(ArchitectureRecommendationError, match="exactly match"):
        service.recommend(document_id)


def test_mermaid_diagrams_validate_their_type(document_id: UUID = uuid4()) -> None:
    with pytest.raises(ValidationError, match="sequenceDiagram"):
        SequenceDiagram(
            **diagram_metadata(document_id, "DIAG-001", "Invalid"),
            mermaid="flowchart LR\n  A --> B",
        )

