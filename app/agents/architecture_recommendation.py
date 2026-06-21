import hashlib
import re
from statistics import fmean
from typing import Protocol

from openai import OpenAI

from app.agents.framework import AgentContext, AgentResult, BaseAgent
from app.models.architecture_blueprint import (
    ArchitectureBlueprint,
    ArchitectureProvenance,
    ArchitectureRecommendationItem,
    ArchitectureRecommendationType,
)
from app.models.assumption_ledger import FrameworkAssumptionLedgerResult
from app.models.engineering_blueprint import EngineeringBlueprintResult
from app.models.requirement_extraction import RequirementExtraction

SYSTEM_PROMPT = """You are the SpecBridge Architecture Recommendation Agent.

Convert the validated Engineering Blueprint into a production-oriented software
Architecture Blueprint. This is Architecture-as-a-Service, not code generation.

Generate:
- one high-level architecture style recommendation among monolith, modular
  monolith, microservices, event driven, serverless, hybrid, or undetermined
- logical modules inferred from the specification
- module/service purpose, responsibilities, dependencies, and public interfaces
- database model, ownership, relationships, access patterns, and partitioning
- supported external integrations
- communication patterns and rationale
- authentication and authorization only when specification evidence supports it
- caching and messaging only when justified
- logging, metrics, tracing, audit, and monitoring recommendations
- deployment, scalability, reliability, and security considerations
- exactly five Mermaid diagrams: system context, component, container,
  sequence, and module dependency

Architecture discipline:
- Prefer the simplest architecture supported by current evidence.
- Do not recommend infrastructure products merely because they are common.
- Do not invent scale, traffic, latency, availability, compliance, cloud,
  region, data residency, team topology, budget, or operational maturity.
- Do not hardcode domain modules. Infer boundaries from requirements,
  workflows, integrations, business rules, and Engineering Blueprint artifacts.
- Authentication, caching, queues, brokers, Kubernetes, serverless, databases,
  and security mechanisms must be evidence-supported recommendations.
- If a decision lacks support, return "Needs clarification" instead of choosing.
- Open or rejected assumptions cannot be used as settled architecture.
- Do not generate implementation code.

Traceability:
- Every recommendation and diagram must cite exact requirement IDs,
  Engineering Blueprint artifact IDs, assumption IDs when applicable, source
  chunks, source sections, confidence, reason, provenance, and traceability.
- Never create assumptions.
- The platform recalculates traceability scores after generation.

Mermaid:
- Sequence diagram begins with sequenceDiagram.
- Other diagrams begin with flowchart or graph.
- Use simple Mermaid without HTML or styling directives.
"""


class ArchitectureBlueprintProvider(Protocol):
    def generate(self, context: str) -> ArchitectureBlueprint:
        """Generate a traceable Architecture Blueprint."""


class OpenAIArchitectureBlueprintProvider:
    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def generate(self, context: str) -> ArchitectureBlueprint:
        response = self._client.responses.parse(
            model=self._model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Generate the Architecture Blueprint from these "
                        f"validated inputs.\n\n{context}"
                    ),
                },
            ],
            text_format=ArchitectureBlueprint,
        )
        if response.output_parsed is None:
            raise RuntimeError("The model returned no Architecture Blueprint.")
        return response.output_parsed


class ArchitectureRecommendationAgent(BaseAgent):
    """Framework generation agent for production-oriented architecture."""

    version = "1"

    def __init__(
        self,
        provider: ArchitectureBlueprintProvider | None = None,
    ) -> None:
        self._provider = provider

    @property
    def name(self) -> str:
        return "architecture_recommendation"

    @property
    def description(self) -> str:
        return "Converts the Engineering Blueprint into architecture guidance."

    def dependencies(self) -> tuple[str, ...]:
        return ("business_to_engineering_translation",)

    def validate(self, context: AgentContext) -> None:
        if not context.chunks:
            raise ValueError("Architecture recommendation requires source chunks.")
        for dependency in (
            "requirement_extraction",
            "assumption_ledger",
            "business_to_engineering_translation",
        ):
            if dependency not in context.results:
                raise ValueError(
                    f"Architecture recommendation requires {dependency} results."
                )
        provider = self._provider or context.llm_provider
        if provider is None or not hasattr(provider, "generate"):
            raise ValueError(
                "Architecture recommendation requires a blueprint provider."
            )

    def cache_fingerprint(self, context: AgentContext) -> str:
        fingerprint = context.configuration.get("source_fingerprint")
        if fingerprint:
            return str(fingerprint)
        payload = context.dna_fingerprint + "".join(
            str(context.results[name].output)
            for name in (
                "requirement_extraction",
                "assumption_ledger",
                "business_to_engineering_translation",
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def execute(self, context: AgentContext) -> AgentResult:
        provider = self._provider or context.llm_provider
        blueprint = provider.generate(self._assemble_context(context))
        blueprint = self._with_scores(blueprint, context)
        self._validate_output(blueprint, context)
        return AgentResult(
            agent_name=self.name,
            output=blueprint.model_dump(mode="json"),
            confidence=fmean(
                [
                    *(item.confidence for item in blueprint.recommendations),
                    *(item.confidence for item in blueprint.diagrams),
                ]
            ),
            source_chunks=list(
                dict.fromkeys(
                    chunk_id
                    for item in [
                        *blueprint.recommendations,
                        *blueprint.diagrams,
                    ]
                    for chunk_id in item.source_chunk_ids
                )
            ),
            assumptions=list(
                dict.fromkeys(
                    assumption_id
                    for item in [
                        *blueprint.recommendations,
                        *blueprint.diagrams,
                    ]
                    for assumption_id in item.related_assumption_ids
                )
            ),
            warnings=[
                f"{item.recommendation_id} needs clarification."
                for item in blueprint.recommendations
                if item.provenance is ArchitectureProvenance.NEEDS_CLARIFICATION
            ],
        )

    @staticmethod
    def _assemble_context(context: AgentContext) -> str:
        parts = [
            "SPECIFICATION_DNA:",
            (
                context.specification_dna.model_dump_json(indent=2)
                if hasattr(context.specification_dna, "model_dump_json")
                else str(context.specification_dna)
            ),
            "REQUIREMENTS:",
            str(context.results["requirement_extraction"].output),
            "ASSUMPTION_LEDGER:",
            str(context.results["assumption_ledger"].output),
            "ENGINEERING_BLUEPRINT:",
            str(context.results["business_to_engineering_translation"].output),
        ]
        if context.knowledge_graph is not None:
            parts.extend(
                [
                    "KNOWLEDGE_GRAPH:",
                    "\n".join(
                        (
                            f"{entity.entity_type.value}|{entity.id}|"
                            f"{entity.title}|{entity.description}|"
                            f"chunks={entity.source_chunk_ids}"
                        )
                        for entity in context.knowledge_graph.entities
                    ),
                ]
            )
        return "\n\n".join(parts)

    @classmethod
    def _with_scores(
        cls,
        blueprint: ArchitectureBlueprint,
        context: AgentContext,
    ) -> ArchitectureBlueprint:
        ledger = FrameworkAssumptionLedgerResult.model_validate(
            context.results["assumption_ledger"].output
        )
        statuses = {
            item.assumption_id: item.status.value for item in ledger.assumptions
        }
        recommendations = [
            item.model_copy(
                update={
                    "traceability_score": cls._score(
                        item.provenance,
                        item.related_assumption_ids,
                        statuses,
                    )
                }
            )
            for item in blueprint.recommendations
        ]
        diagrams = [
            item.model_copy(
                update={
                    "traceability_score": cls._score(
                        item.provenance,
                        item.related_assumption_ids,
                        statuses,
                    )
                }
            )
            for item in blueprint.diagrams
        ]
        return blueprint.model_copy(
            update={"recommendations": recommendations, "diagrams": diagrams}
        )

    @staticmethod
    def _score(
        provenance: ArchitectureProvenance,
        assumption_ids: list[str],
        statuses: dict[str, str],
    ) -> float:
        if provenance is ArchitectureProvenance.DOCUMENT_BACKED:
            return 1.0
        if provenance is ArchitectureProvenance.AI_RECOMMENDATION:
            return 0.85
        if provenance is ArchitectureProvenance.AI_ASSUMPTION:
            return (
                0.75
                if assumption_ids
                and all(statuses.get(item) == "confirmed" for item in assumption_ids)
                else 0.6
            )
        return 0.55

    @classmethod
    def _validate_output(
        cls,
        blueprint: ArchitectureBlueprint,
        context: AgentContext,
    ) -> None:
        requirements = RequirementExtraction.model_validate(
            context.results["requirement_extraction"].output
        ).requirements
        requirement_map = {item.requirement_id: item for item in requirements}
        engineering = EngineeringBlueprintResult.model_validate(
            context.results["business_to_engineering_translation"].output
        )
        artifacts = {
            artifact.artifact_id: artifact
            for requirement_blueprint in engineering.requirement_blueprints
            for artifact in requirement_blueprint.artifacts
        }
        assumptions = FrameworkAssumptionLedgerResult.model_validate(
            context.results["assumption_ledger"].output
        )
        statuses = {
            item.assumption_id: item.status.value for item in assumptions.assumptions
        }
        chunk_map = {chunk.id: chunk for chunk in context.chunks}
        identifiers = [
            *(item.recommendation_id for item in blueprint.recommendations),
            *(item.diagram_id for item in blueprint.diagrams),
        ]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Architecture recommendation and diagram IDs must be unique.")
        for item in [*blueprint.recommendations, *blueprint.diagrams]:
            cls._validate_traceability(
                item,
                requirement_map,
                artifacts,
                statuses,
                chunk_map,
            )
        high_level = [
            item
            for item in blueprint.recommendations
            if item.recommendation_type
            is ArchitectureRecommendationType.HIGH_LEVEL_ARCHITECTURE
        ]
        if len(high_level) != 1:
            raise ValueError(
                "Architecture Blueprint requires one high-level recommendation."
            )
        style = high_level[0].details.get("style")
        if style != blueprint.recommended_style.value:
            raise ValueError(
                "High-level recommendation details must match recommended_style."
            )

    @classmethod
    def _validate_traceability(
        cls,
        item: object,
        requirement_map: dict[str, object],
        artifacts: dict[str, object],
        assumption_statuses: dict[str, str],
        chunk_map: dict[str, object],
    ) -> None:
        unknown_requirements = set(item.related_requirement_ids) - set(
            requirement_map
        )
        if unknown_requirements:
            raise ValueError(
                "Architecture references unknown requirements: "
                + ", ".join(sorted(unknown_requirements))
            )
        unknown_artifacts = set(item.related_artifact_ids) - set(artifacts)
        if unknown_artifacts:
            raise ValueError(
                "Architecture references unknown engineering artifacts: "
                + ", ".join(sorted(unknown_artifacts))
            )
        unknown_assumptions = set(item.related_assumption_ids) - set(
            assumption_statuses
        )
        if unknown_assumptions:
            raise ValueError(
                "Architecture references unknown assumptions: "
                + ", ".join(sorted(unknown_assumptions))
            )
        expected_chunks = {
            chunk_id
            for requirement_id in item.related_requirement_ids
            for chunk_id in requirement_map[requirement_id].source_chunk_ids
        }
        expected_sections = {
            requirement_map[requirement_id].source_section
            for requirement_id in item.related_requirement_ids
        }
        if set(item.source_chunk_ids) != expected_chunks:
            raise ValueError(
                "Architecture source chunks must exactly match requirements."
            )
        if set(item.source_sections) != expected_sections:
            raise ValueError(
                "Architecture source sections must exactly match requirements."
            )
        if not expected_chunks.issubset(chunk_map):
            raise ValueError("Architecture references unknown source chunks.")
        if item.provenance is ArchitectureProvenance.DOCUMENT_BACKED:
            evidence = getattr(item, "evidence_text", None)
            source = cls._normalize(
                "\n".join(chunk_map[chunk_id].text for chunk_id in expected_chunks)
            )
            if not evidence or cls._normalize(evidence) not in source:
                raise ValueError(
                    "Document-backed architecture evidence was not found."
                )
        if item.provenance is ArchitectureProvenance.AI_ASSUMPTION:
            if any(
                assumption_statuses[assumption_id] != "confirmed"
                for assumption_id in item.related_assumption_ids
            ):
                raise ValueError(
                    "Architecture cannot settle open or rejected assumptions."
                )

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip().casefold()
