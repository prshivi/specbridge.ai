from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agents.business_to_engineering import (
    BusinessToEngineeringTranslationAgent,
)
from app.agents.framework import AgentContext, AgentPipelineEngine, AgentRegistry, AgentResult
from app.api.routes import engineering as engineering_route
from app.core.config import Settings
from app.main import app
from app.models.assumption_ledger import FrameworkAssumptionLedgerResult
from app.models.engineering_blueprint import (
    AcceptanceCriterionPayload,
    ArtifactProvenance,
    BlueprintArtifact,
    BlueprintHttpMethod,
    BusinessRulePayload,
    BusinessToEngineeringOutput,
    ConsiderationPayload,
    DatabaseEntityPayload,
    EngineeringArtifactType,
    EngineeringField,
    EngineeringSummaryPayload,
    OpenQuestionPayload,
    RequirementEngineeringBlueprint,
    RestApiPayload,
    ScenarioPayload,
    TaskPayload,
    TechnicalRiskPayload,
    UserStoryPayload,
)
from app.models.knowledge import EntityType, KnowledgeEntity
from app.services.business_to_engineering import (
    BusinessToEngineeringTranslationService,
)
from app.services.engineering_blueprint_store import EngineeringBlueprintStore
from app.services.knowledge_store import KnowledgeGraphStore
from app.tests.test_framework_assumption_ledger import (
    StubAmbiguityService,
    StubAssumptionProvider,
    StubMissingService,
    build_ambiguities,
    build_assumption_output,
    build_missing_result,
)
from app.tests.test_missing_requirement_detection import (
    StubChunkService,
    StubConflictService,
    StubDNAService,
    StubKnowledgeService,
    StubRequirementService,
    build_empty_conflicts,
    build_missing_chunks,
    build_missing_graph,
    build_missing_requirements,
)
from app.tests.test_specification_dna_agent import build_specification_dna


class StubLedgerService:
    def __init__(self, result: FrameworkAssumptionLedgerResult) -> None:
        self.result = result

    def list(self, document_id: UUID) -> FrameworkAssumptionLedgerResult:
        assert document_id == self.result.document_id
        return self.result


class StubBlueprintProvider:
    def __init__(self, output: BusinessToEngineeringOutput) -> None:
        self.output = output
        self.calls = 0
        self.context = ""

    def generate(self, context: str) -> BusinessToEngineeringOutput:
        self.calls += 1
        self.context = context
        return self.output


def build_ledger_result(document_id: UUID) -> FrameworkAssumptionLedgerResult:
    output = build_assumption_output(document_id)
    return FrameworkAssumptionLedgerResult(
        document_id=document_id,
        facts=output.facts,
        assumptions=output.assumptions,
        cached=True,
        model="assumption-model",
        agent_version="1",
        source_fingerprint="assumption-v1",
        execution_time_ms=0,
        analyzed_at=datetime.now(UTC),
        knowledge_graph_updated=True,
    )


def metadata(
    document_id: UUID,
    artifact_id: str,
    artifact_type: EngineeringArtifactType,
    *,
    provenance: ArtifactProvenance = ArtifactProvenance.AI_SUGGESTION,
    ambiguity: bool = False,
    missing: bool = False,
) -> dict[str, object]:
    return {
        "artifact_id": artifact_id,
        "requirement_id": "INT-001",
        "artifact_type": artifact_type,
        "title": artifact_id.replace("-", " ").title(),
        "description": f"Engineering specification for {artifact_type.value}.",
        "provenance": provenance,
        "confidence": 0.84,
        "evidence_text": None,
        "suggestion_reason": (
            "Organizes the explicit requirement into an implementation-ready "
            "engineering specification."
            if provenance is ArtifactProvenance.AI_SUGGESTION
            else None
        ),
        "source_chunk_ids": [f"{document_id}:1"],
        "source_sections": ["3.1"],
        "related_assumption_ids": [],
        "related_ambiguity_ids": ["AMB-001"] if ambiguity else [],
        "related_conflict_ids": [],
        "related_missing_requirement_ids": ["MISS-001"] if missing else [],
        "traceability_score": 0.1,
    }


def build_blueprint_output(document_id: UUID) -> BusinessToEngineeringOutput:
    evidence = (
        "The registration workflow sends validated account details to Email Provider."
    )
    summary_metadata = metadata(
        document_id,
        "ENG-SUM-001",
        EngineeringArtifactType.ENGINEERING_SUMMARY,
        provenance=ArtifactProvenance.DOCUMENT_BACKED,
    )
    summary_metadata.update(
        {
            "description": "The system sends validated account details externally.",
            "evidence_text": evidence,
            "suggestion_reason": None,
            "confidence": 0.96,
        }
    )
    artifacts = [
        BlueprintArtifact(
            **summary_metadata,
            payload=EngineeringSummaryPayload(summary=(
                "Transmit validated account details to Email Provider."
            )),
        ),
        BlueprintArtifact(
            **metadata(
                document_id,
                "US-001",
                EngineeringArtifactType.USER_STORY,
            ),
            payload=UserStoryPayload(
                actor="Registration workflow participant",
                goal="send validated account details",
                benefit="the external notification step can complete",
                story=(
                    "As a registration workflow participant, I want validated "
                    "account details sent so that the external notification step "
                    "can complete."
                ),
            ),
        ),
        BlueprintArtifact(
            **metadata(
                document_id,
                "AC-001",
                EngineeringArtifactType.ACCEPTANCE_CRITERION,
            ),
            payload=AcceptanceCriterionPayload(
                given="Validated account details are available",
                when="The registration integration step executes",
                then="The details are sent to Email Provider",
                measurable_outcome=(
                    "One provider request is recorded for the workflow step."
                ),
            ),
        ),
        BlueprintArtifact(
            **metadata(
                document_id,
                "TASK-BE-001",
                EngineeringArtifactType.BACKEND_TASK,
            ),
            payload=TaskPayload(
                kind=EngineeringArtifactType.BACKEND_TASK,
                task="Implement the provider handoff boundary",
                deliverables=["Provider request mapping", "Execution logging"],
                dependencies=[],
            ),
        ),
        BlueprintArtifact(
            **metadata(
                document_id,
                "API-001",
                EngineeringArtifactType.REST_API,
            ),
            payload=RestApiPayload(
                endpoint="/registrations/{registration_id}/notifications",
                method=BlueprintHttpMethod.POST,
                purpose="Trigger the specified provider handoff",
                request_fields=[],
                response_fields=[],
                status_codes={},
                authentication_needed=None,
                validation_rules=["Use only validated account details"],
            ),
        ),
        BlueprintArtifact(
            **metadata(
                document_id,
                "DB-001",
                EngineeringArtifactType.DATABASE_ENTITY,
            ),
            payload=DatabaseEntityPayload(
                entity="ProviderHandoffRecord",
                attributes=[],
                relationships=[],
                primary_key=None,
                foreign_keys=[],
                constraints=["Needs clarification before persistence design"],
            ),
        ),
        BlueprintArtifact(
            **metadata(
                document_id,
                "RULE-001",
                EngineeringArtifactType.BUSINESS_RULE,
            ),
            payload=BusinessRulePayload(
                rule="Only validated account details are sent.",
                engineering_interpretation=(
                    "The handoff must occur after validation succeeds."
                ),
            ),
        ),
        BlueprintArtifact(
            **metadata(
                document_id,
                "EDGE-001",
                EngineeringArtifactType.EDGE_CASE,
                ambiguity=True,
            ),
            payload=ScenarioPayload(
                kind=EngineeringArtifactType.EDGE_CASE,
                scenario="No validated details are available",
                expected_behavior="Do not initiate the provider handoff.",
            ),
        ),
        BlueprintArtifact(
            **metadata(
                document_id,
                "FAIL-001",
                EngineeringArtifactType.FAILURE_SCENARIO,
                ambiguity=True,
                missing=True,
            ),
            payload=ScenarioPayload(
                kind=EngineeringArtifactType.FAILURE_SCENARIO,
                scenario="Email Provider is unavailable",
                expected_behavior="Needs clarification before implementation.",
            ),
        ),
        BlueprintArtifact(
            **metadata(
                document_id,
                "TASK-INT-001",
                EngineeringArtifactType.INTEGRATION_TASK,
            ),
            payload=TaskPayload(
                kind=EngineeringArtifactType.INTEGRATION_TASK,
                task="Define the Email Provider adapter contract",
                deliverables=["Request mapping", "Response mapping"],
                dependencies=["Provider contract clarification"],
            ),
        ),
        BlueprintArtifact(
            **metadata(
                document_id,
                "SEC-001",
                EngineeringArtifactType.SECURITY_CONSIDERATION,
            ),
            payload=ConsiderationPayload(
                kind=EngineeringArtifactType.SECURITY_CONSIDERATION,
                consideration="Account details cross a system boundary.",
                engineering_action=(
                    "Needs clarification on required transport and access controls."
                ),
            ),
        ),
        BlueprintArtifact(
            **metadata(
                document_id,
                "PERF-001",
                EngineeringArtifactType.PERFORMANCE_CONSIDERATION,
            ),
            payload=ConsiderationPayload(
                kind=EngineeringArtifactType.PERFORMANCE_CONSIDERATION,
                consideration="The handoff is part of a registration workflow.",
                engineering_action="Measure provider call duration separately.",
            ),
        ),
        BlueprintArtifact(
            **metadata(
                document_id,
                "RISK-001",
                EngineeringArtifactType.TECHNICAL_RISK,
                ambiguity=True,
                missing=True,
            ),
            payload=TechnicalRiskPayload(
                risk="Undefined provider failure behavior",
                impact="Registration completion behavior cannot be finalized.",
                mitigation_or_question="Confirm retry and failure outcomes.",
            ),
        ),
    ]
    question_metadata = metadata(
        document_id,
        "Q-001",
        EngineeringArtifactType.OPEN_QUESTION,
        provenance=ArtifactProvenance.NEEDS_CLARIFICATION,
        ambiguity=True,
        missing=True,
    )
    question_metadata.update(
        {
            "description": (
                "Needs clarification: provider failure behavior is undefined."
            ),
            "suggestion_reason": None,
            "confidence": 0.7,
        }
    )
    artifacts.append(
        BlueprintArtifact(
            **question_metadata,
            payload=OpenQuestionPayload(
                missing_information="Provider failure and retry behavior",
                question=(
                    "What should happen when Email Provider is unavailable?"
                ),
                recommended_stakeholder="product",
            ),
        )
    )
    return BusinessToEngineeringOutput(
        requirement_blueprints=[
            RequirementEngineeringBlueprint(
                requirement_id="INT-001",
                requirement_title="Send account details",
                artifacts=artifacts,
            )
        ]
    )


def build_context(
    document_id: UUID,
    provider: StubBlueprintProvider,
) -> AgentContext:
    requirements = build_missing_requirements(document_id)
    ambiguities = build_ambiguities(document_id)
    conflicts = build_empty_conflicts(document_id)
    missing = build_missing_result(document_id)
    assumptions = build_ledger_result(document_id)
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
            "assumption_ledger": AgentResult(
                agent_name="assumption_ledger",
                output=assumptions.model_dump(mode="json"),
                confidence=1.0,
            ),
        },
    )


def build_service(
    tmp_path: Path,
    document_id: UUID,
    provider: StubBlueprintProvider,
) -> BusinessToEngineeringTranslationService:
    settings = Settings(
        agent_framework_db=tmp_path / "agents.db",
        understanding_cache_db=tmp_path / "knowledge.db",
        openai_translator_model="test-blueprint-model",
        agent_retry_attempts=1,
        _env_file=None,
    )
    graph = build_missing_graph(document_id)
    graph.entities.extend(
        [
            KnowledgeEntity(
                id=f"kg:{document_id}:ambiguity_issue:amb-001",
                document_id=document_id,
                entity_type=EntityType.AMBIGUITY_ISSUE,
                title="Missing error handling",
                description="Provider failure behavior is not stated.",
                source_chunk_ids=[f"{document_id}:1"],
                confidence=0.9,
                metadata={"ambiguity_id": "AMB-001"},
            ),
            KnowledgeEntity(
                id=f"kg:{document_id}:missing_requirement_issue:miss-001",
                document_id=document_id,
                entity_type=EntityType.MISSING_REQUIREMENT_ISSUE,
                title="Missing provider failure handling",
                description="Failure behavior is missing.",
                source_chunk_ids=[f"{document_id}:1"],
                confidence=0.82,
                metadata={"missing_requirement_id": "MISS-001"},
            ),
        ]
    )
    graph_store = KnowledgeGraphStore(settings.understanding_cache_db)
    graph_store.replace(graph)
    return BusinessToEngineeringTranslationService(
        settings,
        chunk_service=StubChunkService(build_missing_chunks(document_id)),
        dna_service=StubDNAService(document_id),
        requirement_service=StubRequirementService(
            build_missing_requirements(document_id)
        ),
        ambiguity_service=StubAmbiguityService(build_ambiguities(document_id)),
        conflict_service=StubConflictService(build_empty_conflicts(document_id)),
        missing_service=StubMissingService(build_missing_result(document_id)),
        assumption_service=StubLedgerService(build_ledger_result(document_id)),
        knowledge_service=StubKnowledgeService(graph),
        knowledge_store=graph_store,
        store=EngineeringBlueprintStore(settings.agent_framework_db),
        provider=provider,
    )


def test_agent_generates_complete_typed_blueprint() -> None:
    document_id = uuid4()
    provider = StubBlueprintProvider(build_blueprint_output(document_id))
    agent = BusinessToEngineeringTranslationAgent(provider)
    registry = AgentRegistry()
    registry.register(agent)

    result = AgentPipelineEngine(registry).execute_agent(
        agent.name,
        build_context(document_id, provider),
    )

    artifacts = result.output["requirement_blueprints"][0]["artifacts"]
    kinds = {item["artifact_type"] for item in artifacts}
    assert len(kinds) == len(EngineeringArtifactType)
    assert artifacts[0]["traceability_score"] == 1.0
    assert any(
        item["provenance"] == "needs_clarification" for item in artifacts
    )
    assert "ASSUMPTION_LEDGER" in provider.context


def test_user_story_schema_requires_requested_format() -> None:
    with pytest.raises(ValidationError, match="User stories"):
        UserStoryPayload(
            actor="Customer",
            goal="register",
            benefit="gain access",
            story="Customer registers.",
        )


def test_agent_rejects_unknown_traceability_id() -> None:
    document_id = uuid4()
    output = build_blueprint_output(document_id)
    output.requirement_blueprints[0].artifacts[0].related_conflict_ids = [
        "CON-999"
    ]
    provider = StubBlueprintProvider(output)
    agent = BusinessToEngineeringTranslationAgent(provider)
    registry = AgentRegistry()
    registry.register(agent)

    with pytest.raises(ValueError, match="unknown conflicts"):
        AgentPipelineEngine(registry).execute_agent(
            agent.name,
            build_context(document_id, provider),
        )


def test_open_assumption_cannot_be_settled_output() -> None:
    document_id = uuid4()
    output = build_blueprint_output(document_id)
    artifact = output.requirement_blueprints[0].artifacts[1]
    artifact.provenance = ArtifactProvenance.AI_ASSUMPTION
    artifact.related_assumption_ids = ["ASM-001"]
    artifact.suggestion_reason = "Depends on the provisional actor assumption."
    provider = StubBlueprintProvider(output)
    agent = BusinessToEngineeringTranslationAgent(provider)
    registry = AgentRegistry()
    registry.register(agent)

    with pytest.raises(ValueError, match="Open assumptions"):
        AgentPipelineEngine(registry).execute_agent(
            agent.name,
            build_context(document_id, provider),
        )


def test_service_persists_caches_and_updates_graph(tmp_path: Path) -> None:
    document_id = uuid4()
    provider = StubBlueprintProvider(build_blueprint_output(document_id))
    service = build_service(tmp_path, document_id, provider)

    result = service.run(document_id)
    cached = service.run(document_id)
    artifact = service.get(document_id, "API-001")

    assert result.total_artifacts == 14
    assert result.clarification_artifacts == 1
    assert cached.cached is True
    assert provider.calls == 1
    assert artifact.payload.kind is EngineeringArtifactType.REST_API
    graph = service._knowledge_store.get(document_id)
    assert graph is not None
    artifact_nodes = [
        item
        for item in graph.entities
        if item.entity_type is EntityType.ENGINEERING_ARTIFACT
    ]
    assert len(artifact_nodes) == 14
    assert any(
        edge.source_id == artifact_nodes[0].id for edge in graph.relationships
    )


client = TestClient(app)


def test_business_to_engineering_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = uuid4()
    service = build_service(
        tmp_path,
        document_id,
        StubBlueprintProvider(build_blueprint_output(document_id)),
    )
    monkeypatch.setattr(
        engineering_route,
        "get_business_to_engineering_service",
        lambda: service,
    )

    run_response = client.post(
        f"/agents/business-to-engineering/{document_id}"
    )
    list_response = client.get(f"/engineering/{document_id}")
    detail_response = client.get(f"/engineering/{document_id}/API-001")

    assert run_response.status_code == 200
    assert list_response.status_code == 200
    assert list_response.json()["total_artifacts"] == 14
    assert detail_response.status_code == 200
    assert detail_response.json()["artifact_type"] == "rest_api"
