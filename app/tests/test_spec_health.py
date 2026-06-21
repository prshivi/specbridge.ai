from uuid import UUID, uuid4

from app.core.config import Settings
from app.services.spec_health import SpecHealthService
from app.tests.test_traceability import (
    StubAmbiguityService,
    StubArchitectureService,
    StubAssumptionService,
    StubConflictService,
    StubRequirementService,
    StubTranslatorService,
    build_traceability_service,
)
from app.tests.test_requirement_intelligence import StubChunkService, build_chunks


def build_spec_health_service(document_id: UUID) -> SpecHealthService:
    return SpecHealthService(
        Settings(mock_ai=False, _env_file=None),
        traceability_service=build_traceability_service(document_id),
        ambiguity_service=StubAmbiguityService(),
        conflict_service=StubConflictService(),
        assumption_service=StubAssumptionService(),
        translator_service=StubTranslatorService(),
        architecture_service=StubArchitectureService(),
    )


def test_spec_health_calculates_all_requested_scores() -> None:
    document_id = uuid4()
    dashboard = build_spec_health_service(document_id).generate(document_id)

    assert {metric.key for metric in dashboard.metrics} == {
        "clarity",
        "completeness",
        "consistency",
        "technical_readiness",
        "architecture_readiness",
        "missing_information",
        "dependencies",
        "edge_cases",
    }
    assert 0 <= dashboard.overall_health.score <= 100
    assert dashboard.statistics.total_requirements == 2
    assert dashboard.statistics.ambiguity_issues == 1
    assert dashboard.statistics.conflicts == 1
    assert dashboard.next_actions
    assert "higher is better" in dashboard.scoring_note


def test_spec_health_recommends_closing_known_gaps() -> None:
    document_id = uuid4()
    dashboard = build_spec_health_service(document_id).generate(document_id)
    actions = " ".join(action.action for action in dashboard.next_actions)

    assert "clarification" in actions.lower()
    assert "conflict" in actions.lower()
    assert "assumption" in actions.lower()
    assert "acceptance criteria" in actions.lower()


def test_mock_spec_health_uses_chunks_without_ai_calls() -> None:
    document_id = uuid4()
    service = SpecHealthService(
        Settings(mock_ai=True, _env_file=None),
        chunk_service=StubChunkService(build_chunks(document_id)),
    )

    dashboard = service.generate(document_id)

    assert dashboard.analysis_mode == "mock"
    assert len(dashboard.metrics) == 8
    assert dashboard.next_actions
    assert "no LLM calls" in dashboard.scoring_note
