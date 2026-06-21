from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agents.assumption_ledger import AssumptionLedgerAgent
from app.agents.framework import AgentContext, AgentPipelineEngine, AgentRegistry, AgentResult
from app.api.routes import assumptions as assumptions_route
from app.core.config import Settings
from app.main import app
from app.models.ambiguity import (
    AmbiguityDetectionResult,
    AmbiguityIssue,
    AmbiguityType,
    IssueSeverity,
    RequirementAmbiguityAssessment,
)
from app.models.assumption_ledger import (
    AssumptionImpactArea,
    AssumptionLedgerOutput,
    AssumptionRiskLevel,
    AssumptionStatus,
    AssumptionStatusUpdate,
    AssumptionType,
    LedgerAssumption,
    LedgerFact,
)
from app.models.missing_requirements import MissingRequirementDetectionResult
from app.services.assumption_ledger_store import FrameworkAssumptionLedgerStore
from app.services.framework_assumptions import FrameworkAssumptionLedgerService
from app.services.knowledge_store import KnowledgeGraphStore
from app.tests.test_missing_requirement_detection import (
    StubChunkService,
    StubConflictService,
    StubDNAService,
    StubKnowledgeService,
    StubRequirementService,
    build_empty_conflicts,
    build_missing_chunks,
    build_missing_graph,
    build_missing_output,
    build_missing_requirements,
)
from app.tests.test_specification_dna_agent import build_specification_dna


class StubAmbiguityService:
    def __init__(self, result: AmbiguityDetectionResult) -> None:
        self.result = result

    def detect(self, document_id: UUID) -> AmbiguityDetectionResult:
        assert document_id == self.result.document_id
        return self.result


class StubMissingService:
    def __init__(self, result: MissingRequirementDetectionResult) -> None:
        self.result = result

    def list(self, document_id: UUID) -> MissingRequirementDetectionResult:
        assert document_id == self.result.document_id
        return self.result


class StubAssumptionProvider:
    def __init__(self, output: AssumptionLedgerOutput) -> None:
        self.output = output
        self.calls = 0
        self.context = ""

    def audit(self, context: str) -> AssumptionLedgerOutput:
        self.calls += 1
        self.context = context
        return self.output


def build_ambiguities(document_id: UUID) -> AmbiguityDetectionResult:
    chunk_id = f"{document_id}:1"
    issue = AmbiguityIssue(
        issue_id="AMB-001",
        requirement_id="INT-001",
        source_chunk=chunk_id,
        issue_type=AmbiguityType.MISSING_ERROR_HANDLING,
        severity=IssueSeverity.HIGH,
        confidence=0.9,
        reason="The integration failure behavior is not stated.",
        clarification_question="What happens when Email Provider fails?",
        recommended_stakeholder="product",
    )
    return AmbiguityDetectionResult(
        document_id=document_id,
        assessments=[
            RequirementAmbiguityAssessment(
                requirement_id="INT-001",
                source_chunk=chunk_id,
                issues=[issue],
            )
        ],
        total_requirements=1,
        total_issues=1,
        cached=True,
        model="ambiguity-model",
        prompt_version="ambiguity-v1",
        analyzed_at=datetime.now(UTC),
    )


def build_missing_result(document_id: UUID) -> MissingRequirementDetectionResult:
    return MissingRequirementDetectionResult(
        document_id=document_id,
        missing_requirements=build_missing_output(document_id).missing_requirements,
        cached=True,
        model="missing-model",
        agent_version="1",
        source_fingerprint="missing-v1",
        execution_time_ms=0,
        analyzed_at=datetime.now(UTC),
        knowledge_graph_updated=True,
    )


def build_assumption_output(document_id: UUID) -> AssumptionLedgerOutput:
    chunk_id = f"{document_id}:1"
    evidence = (
        "The registration workflow sends validated account details to Email Provider."
    )
    return AssumptionLedgerOutput(
        facts=[
            LedgerFact(
                fact_id="FACT-001",
                title="Email integration exists",
                description="The registration workflow sends account details externally.",
                evidence_text=evidence,
                source_chunk_ids=[chunk_id],
                source_sections=["3.1"],
                related_requirement_ids=["INT-001"],
            )
        ],
        assumptions=[
            LedgerAssumption(
                assumption_id="ASM-001",
                title="Email delivery failure needs a defined outcome",
                description=(
                    "A provisional failure outcome will be needed before the "
                    "integration can be implemented."
                ),
                assumption_type=AssumptionType.ERROR_HANDLING,
                confidence=0.78,
                reason=(
                    "The integration is explicit, while failure behavior is "
                    "flagged as missing."
                ),
                evidence_text=evidence,
                source_chunk_ids=[chunk_id],
                source_sections=["3.1"],
                related_requirement_ids=["INT-001"],
                related_ambiguity_ids=["AMB-001"],
                related_conflict_ids=[],
                related_missing_requirement_ids=["MISS-001"],
                impact_area=AssumptionImpactArea.BACKEND,
                risk_level=AssumptionRiskLevel.HIGH,
                needs_stakeholder_confirmation=True,
                confirmation_question=(
                    "What outcome should occur when Email Provider is unavailable?"
                ),
                status=AssumptionStatus.OPEN,
            )
        ],
    )


def build_context(
    document_id: UUID,
    provider: StubAssumptionProvider,
) -> AgentContext:
    requirements = build_missing_requirements(document_id)
    ambiguities = build_ambiguities(document_id)
    conflicts = build_empty_conflicts(document_id)
    missing = build_missing_result(document_id)
    return AgentContext(
        specification_dna=build_specification_dna(document_id),
        knowledge_graph=build_missing_graph(document_id),
        chunks=build_missing_chunks(document_id),
        llm_provider=provider,
        results={
            "requirement_extraction": AgentResult(
                agent_name="requirement_extraction",
                output={
                    "requirements": [
                        item.model_dump(mode="json")
                        for item in requirements.requirements
                    ]
                },
                confidence=1.0,
            ),
            "ambiguity_detection": AgentResult(
                agent_name="ambiguity_detection",
                output=ambiguities.model_dump(mode="json"),
                confidence=1.0,
            ),
            "conflict_detection": AgentResult(
                agent_name="conflict_detection",
                output={"conflicts": []},
                confidence=1.0,
            ),
            "missing_requirement_detection": AgentResult(
                agent_name="missing_requirement_detection",
                output={
                    "missing_requirements": [
                        item.model_dump(mode="json")
                        for item in missing.missing_requirements
                    ]
                },
                confidence=1.0,
            ),
        },
    )


def build_service(
    tmp_path: Path,
    document_id: UUID,
    provider: StubAssumptionProvider,
) -> FrameworkAssumptionLedgerService:
    settings = Settings(
        agent_framework_db=tmp_path / "agents.db",
        understanding_cache_db=tmp_path / "knowledge.db",
        openai_assumption_model="test-assumption-model",
        agent_retry_attempts=1,
        _env_file=None,
    )
    graph = build_missing_graph(document_id)
    graph_store = KnowledgeGraphStore(settings.understanding_cache_db)
    graph_store.replace(graph)
    return FrameworkAssumptionLedgerService(
        settings,
        chunk_service=StubChunkService(build_missing_chunks(document_id)),
        dna_service=StubDNAService(document_id),
        requirement_service=StubRequirementService(
            build_missing_requirements(document_id)
        ),
        ambiguity_service=StubAmbiguityService(build_ambiguities(document_id)),
        conflict_service=StubConflictService(build_empty_conflicts(document_id)),
        missing_service=StubMissingService(build_missing_result(document_id)),
        knowledge_service=StubKnowledgeService(graph),
        knowledge_store=graph_store,
        store=FrameworkAssumptionLedgerStore(settings.agent_framework_db),
        provider=provider,
    )


def test_agent_executes_and_separates_facts_from_assumptions() -> None:
    document_id = uuid4()
    provider = StubAssumptionProvider(build_assumption_output(document_id))
    agent = AssumptionLedgerAgent(provider)
    registry = AgentRegistry()
    registry.register(agent)

    result = AgentPipelineEngine(registry).execute_agent(
        agent.name,
        build_context(document_id, provider),
    )

    assert result.output["facts"][0]["fact_id"] == "FACT-001"
    assert result.output["assumptions"][0]["status"] == "open"
    assert result.assumptions == ["ASM-001"]
    assert "AMBIGUITIES" in provider.context


def test_schema_requires_confirmation_question() -> None:
    document_id = uuid4()
    payload = build_assumption_output(document_id).assumptions[0].model_dump()
    payload["confirmation_question"] = "Please confirm"

    with pytest.raises(ValidationError, match="must end"):
        LedgerAssumption.model_validate(payload)


def test_agent_rejects_fact_repeated_as_assumption() -> None:
    document_id = uuid4()
    output = build_assumption_output(document_id)
    output.assumptions[0].description = output.facts[0].description
    provider = StubAssumptionProvider(output)
    agent = AssumptionLedgerAgent(provider)
    registry = AgentRegistry()
    registry.register(agent)

    with pytest.raises(ValueError, match="cannot also be stored"):
        AgentPipelineEngine(registry).execute_agent(
            agent.name,
            build_context(document_id, provider),
        )


def test_service_persists_traceability_graph_and_status(tmp_path: Path) -> None:
    document_id = uuid4()
    provider = StubAssumptionProvider(build_assumption_output(document_id))
    service = build_service(tmp_path, document_id, provider)

    result = service.run(document_id)
    cached = service.run(document_id)
    confirmed = service.update_status(
        document_id,
        "ASM-001",
        AssumptionStatus.CONFIRMED,
    )

    assert result.assumptions[0].related_ambiguity_ids == ["AMB-001"]
    assert cached.cached is True
    assert provider.calls == 1
    assert confirmed.status is AssumptionStatus.CONFIRMED
    graph = service._knowledge_store.get(document_id)
    assert graph is not None
    assumption_node = next(
        item
        for item in graph.entities
        if item.entity_type.value == "assumption"
    )
    assert assumption_node.metadata["status"] == "confirmed"
    assert any(
        edge.source_id == assumption_node.id for edge in graph.relationships
    )


def test_status_patch_rejects_open() -> None:
    with pytest.raises(ValidationError, match="confirmed or rejected"):
        AssumptionStatusUpdate(status=AssumptionStatus.OPEN)


client = TestClient(app)


def test_assumption_routes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    document_id = uuid4()
    service = build_service(
        tmp_path,
        document_id,
        StubAssumptionProvider(build_assumption_output(document_id)),
    )
    monkeypatch.setattr(
        assumptions_route,
        "get_framework_assumption_service",
        lambda: service,
    )

    run_response = client.post(f"/agents/assumptions/{document_id}")
    list_response = client.get(f"/assumptions/{document_id}")
    detail_response = client.get(f"/assumptions/{document_id}/ASM-001")
    patch_response = client.patch(
        f"/assumptions/{document_id}/ASM-001",
        json={"status": "rejected"},
    )

    assert run_response.status_code == 200
    assert list_response.status_code == 200
    assert detail_response.json()["related_missing_requirement_ids"] == [
        "MISS-001"
    ]
    assert patch_response.status_code == 200
    assert patch_response.json()["status"] == "rejected"
