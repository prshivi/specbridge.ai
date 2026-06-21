from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agents.architecture_recommendation import (
    ArchitectureRecommendationAgent,
)
from app.agents.framework import AgentContext, AgentPipelineEngine, AgentRegistry, AgentResult
from app.api.routes import architecture as architecture_route
from app.core.config import Settings
from app.main import app
from app.models.architecture_blueprint import (
    ArchitectureBlueprint,
    ArchitectureDiagram,
    ArchitectureDiagramType,
    ArchitectureProvenance,
    ArchitectureRecommendationItem,
    ArchitectureRecommendationType,
    SolutionArchitectureStyle,
)
from app.models.engineering_blueprint import EngineeringBlueprintResult
from app.models.knowledge import EntityType
from app.services.architecture_blueprint_store import ArchitectureBlueprintStore
from app.services.framework_architecture import (
    FrameworkArchitectureRecommendationService,
)
from app.services.knowledge_store import KnowledgeGraphStore
from app.tests.test_business_to_engineering_agent import (
    StubBlueprintProvider,
    StubLedgerService,
    build_blueprint_output,
    build_ledger_result,
    build_service as build_engineering_service,
)
from app.tests.test_missing_requirement_detection import (
    StubChunkService,
    StubDNAService,
    StubKnowledgeService,
    StubRequirementService,
    build_missing_chunks,
    build_missing_requirements,
)
from app.tests.test_specification_dna_agent import build_specification_dna


class StubEngineeringService:
    def __init__(self, result: EngineeringBlueprintResult) -> None:
        self.result = result

    def list(self, document_id: UUID) -> EngineeringBlueprintResult:
        assert document_id == self.result.document_id
        return self.result


class StubArchitectureProvider:
    def __init__(self, blueprint: ArchitectureBlueprint) -> None:
        self.blueprint = blueprint
        self.calls = 0
        self.context = ""

    def generate(self, context: str) -> ArchitectureBlueprint:
        self.calls += 1
        self.context = context
        return self.blueprint


def architecture_metadata(
    document_id: UUID,
    recommendation_id: str,
    recommendation_type: ArchitectureRecommendationType,
) -> dict[str, object]:
    return {
        "recommendation_id": recommendation_id,
        "recommendation_type": recommendation_type,
        "title": recommendation_type.value.replace("_", " ").title(),
        "recommendation": (
            "Use the simplest supported design and revisit when requirements "
            "provide stronger operational evidence."
        ),
        "confidence": 0.82,
        "reason": (
            "The Engineering Blueprint describes one cohesive workflow and one "
            "external integration without independent scaling requirements."
        ),
        "provenance": ArchitectureProvenance.AI_RECOMMENDATION,
        "evidence_text": None,
        "related_requirement_ids": ["INT-001"],
        "related_artifact_ids": ["ENG-SUM-001"],
        "related_assumption_ids": [],
        "source_chunk_ids": [f"{document_id}:1"],
        "source_sections": ["3.1"],
        "traceability_score": 0.1,
        "details": {},
    }


def build_architecture_blueprint(document_id: UUID) -> ArchitectureBlueprint:
    recommendations = []
    for index, recommendation_type in enumerate(
        ArchitectureRecommendationType,
        start=1,
    ):
        values = architecture_metadata(
            document_id,
            f"ARCH-{index:03d}",
            recommendation_type,
        )
        if (
            recommendation_type
            is ArchitectureRecommendationType.HIGH_LEVEL_ARCHITECTURE
        ):
            values["recommendation"] = (
                "Use a modular monolith with an explicit integration boundary."
            )
            values["details"] = {
                "style": "modular_monolith",
                "rejected_styles": ["microservices", "serverless"],
                "evolution_trigger": (
                    "Independent scaling, fault isolation, or release ownership."
                ),
            }
        elif recommendation_type is ArchitectureRecommendationType.MODULE:
            values["details"] = {
                "module": "Registration Integration",
                "purpose": "Coordinate validated account-detail delivery.",
                "responsibilities": ["Prepare and send validated details"],
                "dependencies": ["Email Provider"],
                "public_interfaces": ["Provider handoff boundary"],
            }
        elif recommendation_type is ArchitectureRecommendationType.DATABASE:
            values["details"] = {
                "model": "Needs clarification",
                "entity_ownership": [],
                "relationships": [],
                "read_write_patterns": [],
                "partitioning": "Not justified by current requirements",
            }
        elif (
            recommendation_type
            is ArchitectureRecommendationType.AUTHENTICATION_AUTHORIZATION
        ):
            values["recommendation"] = (
                "Needs clarification: no authentication or authorization "
                "requirements are specified."
            )
            values["provenance"] = ArchitectureProvenance.NEEDS_CLARIFICATION
        recommendations.append(ArchitectureRecommendationItem(**values))

    diagrams = []
    for index, diagram_type in enumerate(ArchitectureDiagramType, start=1):
        mermaid = (
            "sequenceDiagram\n"
            "  participant Registration\n"
            "  participant EmailProvider\n"
            "  Registration->>EmailProvider: Send validated details"
            if diagram_type is ArchitectureDiagramType.SEQUENCE
            else (
                "flowchart LR\n"
                "  User --> Registration\n"
                "  Registration --> EmailProvider"
            )
        )
        diagrams.append(
            ArchitectureDiagram(
                diagram_id=f"DIAG-{index:03d}",
                diagram_type=diagram_type,
                title=diagram_type.value.replace("_", " ").title(),
                mermaid=mermaid,
                confidence=0.82,
                reason="Visualizes only the requirement-supported workflow.",
                provenance=ArchitectureProvenance.AI_RECOMMENDATION,
                related_requirement_ids=["INT-001"],
                related_artifact_ids=["ENG-SUM-001"],
                related_assumption_ids=[],
                source_chunk_ids=[f"{document_id}:1"],
                source_sections=["3.1"],
                traceability_score=0.1,
            )
        )
    return ArchitectureBlueprint(
        summary=(
            "A modular monolith keeps the current workflow cohesive while "
            "preserving an explicit external integration boundary."
        ),
        recommended_style=SolutionArchitectureStyle.MODULAR_MONOLITH,
        recommendations=recommendations,
        diagrams=diagrams,
    )


def build_engineering_result(
    tmp_path: Path,
    document_id: UUID,
) -> tuple[EngineeringBlueprintResult, object]:
    engineering_service = build_engineering_service(
        tmp_path,
        document_id,
        StubBlueprintProvider(build_blueprint_output(document_id)),
    )
    result = engineering_service.run(document_id)
    graph = engineering_service._knowledge_store.get(document_id)
    assert graph is not None
    return result, graph


def build_context(
    document_id: UUID,
    provider: StubArchitectureProvider,
    engineering: EngineeringBlueprintResult,
    graph: object,
) -> AgentContext:
    requirements = build_missing_requirements(document_id)
    assumptions = build_ledger_result(document_id)
    return AgentContext(
        specification_dna=build_specification_dna(document_id),
        knowledge_graph=graph,
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
            "assumption_ledger": AgentResult(
                agent_name="assumption_ledger",
                output=assumptions.model_dump(mode="json"),
                confidence=1.0,
            ),
            "business_to_engineering_translation": AgentResult(
                agent_name="business_to_engineering_translation",
                output=engineering.model_dump(mode="json"),
                confidence=1.0,
            ),
        },
    )


def build_service(
    tmp_path: Path,
    document_id: UUID,
    provider: StubArchitectureProvider,
) -> FrameworkArchitectureRecommendationService:
    engineering, graph = build_engineering_result(tmp_path, document_id)
    settings = Settings(
        agent_framework_db=tmp_path / "agents.db",
        understanding_cache_db=tmp_path / "knowledge.db",
        openai_architecture_model="test-architecture-blueprint-model",
        agent_retry_attempts=1,
        _env_file=None,
    )
    graph_store = KnowledgeGraphStore(settings.understanding_cache_db)
    return FrameworkArchitectureRecommendationService(
        settings,
        chunk_service=StubChunkService(build_missing_chunks(document_id)),
        dna_service=StubDNAService(document_id),
        requirement_service=StubRequirementService(
            build_missing_requirements(document_id)
        ),
        assumption_service=StubLedgerService(build_ledger_result(document_id)),
        engineering_service=StubEngineeringService(engineering),
        knowledge_service=StubKnowledgeService(graph),
        knowledge_store=graph_store,
        store=ArchitectureBlueprintStore(settings.agent_framework_db),
        provider=provider,
    )


def test_agent_generates_complete_architecture_and_diagrams(tmp_path: Path) -> None:
    document_id = uuid4()
    engineering, graph = build_engineering_result(tmp_path, document_id)
    provider = StubArchitectureProvider(build_architecture_blueprint(document_id))
    agent = ArchitectureRecommendationAgent(provider)
    registry = AgentRegistry()
    registry.register(agent)

    result = AgentPipelineEngine(registry).execute_agent(
        agent.name,
        build_context(document_id, provider, engineering, graph),
    )

    architecture = result.output
    assert architecture["recommended_style"] == "modular_monolith"
    assert len(architecture["recommendations"]) == 14
    assert len(architecture["diagrams"]) == 5
    assert {item["diagram_type"] for item in architecture["diagrams"]} == {
        item.value for item in ArchitectureDiagramType
    }
    assert "ENGINEERING_BLUEPRINT" in provider.context


def test_schema_rejects_wrong_sequence_diagram() -> None:
    document_id = uuid4()
    with pytest.raises(ValidationError, match="sequenceDiagram"):
        ArchitectureDiagram(
            diagram_id="DIAG-001",
            diagram_type=ArchitectureDiagramType.SEQUENCE,
            title="Sequence",
            mermaid="flowchart LR\n A --> B",
            confidence=0.8,
            reason="Invalid test diagram.",
            provenance=ArchitectureProvenance.AI_RECOMMENDATION,
            related_requirement_ids=["INT-001"],
            related_artifact_ids=["ENG-SUM-001"],
            source_chunk_ids=[f"{document_id}:1"],
            source_sections=["3.1"],
            traceability_score=0.8,
        )


def test_agent_rejects_unknown_artifact_traceability(tmp_path: Path) -> None:
    document_id = uuid4()
    engineering, graph = build_engineering_result(tmp_path, document_id)
    blueprint = build_architecture_blueprint(document_id)
    blueprint.recommendations[0].related_artifact_ids = ["UNKNOWN"]
    provider = StubArchitectureProvider(blueprint)
    agent = ArchitectureRecommendationAgent(provider)
    registry = AgentRegistry()
    registry.register(agent)

    with pytest.raises(ValueError, match="unknown engineering artifacts"):
        AgentPipelineEngine(registry).execute_agent(
            agent.name,
            build_context(document_id, provider, engineering, graph),
        )


def test_service_persists_cache_graph_and_diagrams(tmp_path: Path) -> None:
    document_id = uuid4()
    provider = StubArchitectureProvider(build_architecture_blueprint(document_id))
    service = build_service(tmp_path, document_id, provider)

    result = service.run(document_id)
    cached = service.run(document_id)
    diagrams = service.diagrams(document_id)

    assert result.total_recommendations == 14
    assert result.total_diagrams == 5
    assert result.clarification_recommendations == 1
    assert cached.cached is True
    assert provider.calls == 1
    assert len(diagrams.diagrams) == 5
    graph = service._knowledge_store.get(document_id)
    assert graph is not None
    nodes = [
        item
        for item in graph.entities
        if item.entity_type is EntityType.ARCHITECTURE_NODE
    ]
    assert len(nodes) == 19
    assert any(
        edge.relationship_type.value == "architecture_edge"
        for edge in graph.relationships
    )


client = TestClient(app)


def test_framework_architecture_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = uuid4()
    service = build_service(
        tmp_path,
        document_id,
        StubArchitectureProvider(build_architecture_blueprint(document_id)),
    )
    monkeypatch.setattr(
        architecture_route,
        "get_framework_architecture_service",
        lambda: service,
    )

    run_response = client.post(f"/agents/architecture/{document_id}")
    get_response = client.get(f"/architecture/{document_id}")
    diagram_response = client.get(f"/architecture/{document_id}/diagram")

    assert run_response.status_code == 200
    assert get_response.status_code == 200
    assert get_response.json()["architecture"]["recommended_style"] == (
        "modular_monolith"
    )
    assert diagram_response.status_code == 200
    assert len(diagram_response.json()["diagrams"]) == 5
