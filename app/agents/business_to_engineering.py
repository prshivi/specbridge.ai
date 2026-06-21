import hashlib
import re
from statistics import fmean
from typing import Protocol

from openai import OpenAI

from app.agents.framework import AgentContext, AgentResult, BaseAgent
from app.models.assumption_ledger import FrameworkAssumptionLedgerResult
from app.models.conflict_detection import ConflictDetectionOutput
from app.models.engineering_blueprint import (
    ArtifactProvenance,
    BlueprintArtifact,
    BusinessToEngineeringOutput,
    EngineeringArtifactType,
)
from app.models.missing_requirements import MissingRequirementDetectionOutput
from app.models.requirement_extraction import RequirementExtraction

SYSTEM_PROMPT = """You are the SpecBridge Business-to-Engineering Translation Agent.

Convert each supplied business requirement into engineering-ready
specifications. This is specification generation, not source-code generation.

For every requirement, consider:
- engineering summary
- user story in "As a ... I want ... So that ..." format
- measurable Given/When/Then acceptance criteria
- backend tasks
- suggested REST APIs
- suggested database entities
- business rules rewritten in engineering language
- edge cases and failure scenarios
- integration tasks
- security and performance considerations
- technical risks
- open questions

Grounding and safety:
- Every artifact belongs to exactly one supplied requirement.
- Preserve exact source chunks and source sections from that requirement.
- Do not generate implementation code.
- Do not invent API behavior, fields, database attributes, actors, rules,
  permissions, integrations, limits, errors, security controls, performance
  targets, or workflow behavior.
- REST APIs and database entities are suggestions, never document-backed,
  unless the document explicitly specifies that exact engineering interface.
- If required information is missing, create an open_question artifact whose
  description explicitly begins with "Needs clarification:".
- It is valid to omit an irrelevant artifact category.
- Never use an open or rejected assumption as settled behavior.

Provenance:
- document_backed: directly supported by verbatim source evidence.
- ai_suggestion: a non-binding engineering organization of explicit behavior;
  include suggestion_reason and no assumption IDs.
- ai_assumption: depends on a stored assumption; include its exact ID and make
  the provisional nature explicit.
- needs_clarification: unresolved information; generate only an open question.

Traceability:
- Cite exact requirement, source chunks, sections, and related issue IDs.
- Related IDs must come from the supplied ledgers.
- Never create a new assumption during translation.
- The platform recalculates traceability_score after generation.
"""


class BusinessToEngineeringProvider(Protocol):
    def generate(self, context: str) -> BusinessToEngineeringOutput:
        """Generate an evidence-grounded engineering blueprint."""


class OpenAIBusinessToEngineeringProvider:
    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def generate(self, context: str) -> BusinessToEngineeringOutput:
        response = self._client.responses.parse(
            model=self._model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Generate the engineering blueprint from these validated "
                        f"inputs.\n\n{context}"
                    ),
                },
            ],
            text_format=BusinessToEngineeringOutput,
        )
        if response.output_parsed is None:
            raise RuntimeError("The model returned no engineering blueprint.")
        return response.output_parsed


class BusinessToEngineeringTranslationAgent(BaseAgent):
    """Framework generation agent for traceable engineering specifications."""

    version = "1"

    def __init__(
        self,
        provider: BusinessToEngineeringProvider | None = None,
    ) -> None:
        self._provider = provider

    @property
    def name(self) -> str:
        return "business_to_engineering_translation"

    @property
    def description(self) -> str:
        return "Converts business requirements into an engineering blueprint."

    def dependencies(self) -> tuple[str, ...]:
        return ("assumption_ledger",)

    def validate(self, context: AgentContext) -> None:
        if not context.chunks:
            raise ValueError("Engineering translation requires document chunks.")
        for dependency in (
            "requirement_extraction",
            "ambiguity_detection",
            "conflict_detection",
            "missing_requirement_detection",
            "assumption_ledger",
        ):
            if dependency not in context.results:
                raise ValueError(
                    f"Engineering translation requires {dependency} results."
                )
        provider = self._provider or context.llm_provider
        if provider is None or not hasattr(provider, "generate"):
            raise ValueError(
                "Engineering translation requires a blueprint provider."
            )

    def cache_fingerprint(self, context: AgentContext) -> str:
        fingerprint = context.configuration.get("source_fingerprint")
        if fingerprint:
            return str(fingerprint)
        payload = context.dna_fingerprint + "".join(
            str(context.results[name].output)
            for name in (
                "requirement_extraction",
                "ambiguity_detection",
                "conflict_detection",
                "missing_requirement_detection",
                "assumption_ledger",
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def execute(self, context: AgentContext) -> AgentResult:
        provider = self._provider or context.llm_provider
        output = provider.generate(self._assemble_context(context))
        output = self._with_traceability_scores(output, context)
        self._validate_output(output, context)
        artifacts = [
            artifact
            for blueprint in output.requirement_blueprints
            for artifact in blueprint.artifacts
        ]
        return AgentResult(
            agent_name=self.name,
            output=output.model_dump(mode="json"),
            confidence=(
                fmean(artifact.confidence for artifact in artifacts)
                if artifacts
                else 0.0
            ),
            source_chunks=list(
                dict.fromkeys(
                    chunk_id
                    for artifact in artifacts
                    for chunk_id in artifact.source_chunk_ids
                )
            ),
            assumptions=list(
                dict.fromkeys(
                    assumption_id
                    for artifact in artifacts
                    for assumption_id in artifact.related_assumption_ids
                )
            ),
            warnings=[
                f"{artifact.artifact_id} needs clarification."
                for artifact in artifacts
                if artifact.provenance is ArtifactProvenance.NEEDS_CLARIFICATION
            ],
        )

    @staticmethod
    def _assemble_context(context: AgentContext) -> str:
        sections = [
            "SPECIFICATION_DNA:",
            (
                context.specification_dna.model_dump_json(indent=2)
                if hasattr(context.specification_dna, "model_dump_json")
                else str(context.specification_dna)
            ),
        ]
        labels = {
            "requirement_extraction": "REQUIREMENTS",
            "ambiguity_detection": "AMBIGUITIES",
            "conflict_detection": "CONFLICTS",
            "missing_requirement_detection": "MISSING_REQUIREMENTS",
            "assumption_ledger": "ASSUMPTION_LEDGER",
        }
        for key, label in labels.items():
            sections.extend([f"{label}:", str(context.results[key].output)])
        if context.knowledge_graph is not None:
            sections.extend(
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
        sections.extend(
            [
                "SOURCE_CHUNKS:",
                "\n".join(
                    (
                        f"{chunk.id}|section="
                        f"{chunk.section or chunk.heading or 'unknown'}|{chunk.text}"
                    )
                    for chunk in context.chunks
                ),
            ]
        )
        return "\n\n".join(sections)

    @classmethod
    def _with_traceability_scores(
        cls,
        output: BusinessToEngineeringOutput,
        context: AgentContext,
    ) -> BusinessToEngineeringOutput:
        assumptions = FrameworkAssumptionLedgerResult.model_validate(
            context.results["assumption_ledger"].output
        )
        statuses = {
            item.assumption_id: item.status.value for item in assumptions.assumptions
        }
        blueprints = []
        for blueprint in output.requirement_blueprints:
            artifacts = [
                artifact.model_copy(
                    update={
                        "traceability_score": cls._traceability_score(
                            artifact,
                            statuses,
                        )
                    }
                )
                for artifact in blueprint.artifacts
            ]
            blueprints.append(blueprint.model_copy(update={"artifacts": artifacts}))
        return output.model_copy(update={"requirement_blueprints": blueprints})

    @staticmethod
    def _traceability_score(
        artifact: BlueprintArtifact,
        assumption_statuses: dict[str, str],
    ) -> float:
        if artifact.provenance is ArtifactProvenance.DOCUMENT_BACKED:
            return 1.0
        if artifact.provenance is ArtifactProvenance.AI_SUGGESTION:
            return 0.85
        if artifact.provenance is ArtifactProvenance.AI_ASSUMPTION:
            statuses = {
                assumption_statuses.get(item) for item in artifact.related_assumption_ids
            }
            return 0.75 if statuses == {"confirmed"} else 0.6
        linked_issues = sum(
            bool(values)
            for values in (
                artifact.related_ambiguity_ids,
                artifact.related_conflict_ids,
                artifact.related_missing_requirement_ids,
            )
        )
        return min(0.7, 0.5 + (linked_issues * 0.05))

    @classmethod
    def _validate_output(
        cls,
        output: BusinessToEngineeringOutput,
        context: AgentContext,
    ) -> None:
        requirements = RequirementExtraction.model_validate(
            context.results["requirement_extraction"].output
        ).requirements
        requirement_map = {item.requirement_id: item for item in requirements}
        blueprint_ids = [
            blueprint.requirement_id for blueprint in output.requirement_blueprints
        ]
        if len(blueprint_ids) != len(set(blueprint_ids)):
            raise ValueError("Each requirement must have one blueprint.")
        if set(blueprint_ids) != set(requirement_map):
            raise ValueError(
                "Engineering output must cover every extracted requirement exactly once."
            )

        ambiguity_ids = cls._ambiguity_ids(
            context.results["ambiguity_detection"].output
        )
        conflict_ids = {
            item.conflict_id
            for item in ConflictDetectionOutput.model_validate(
                context.results["conflict_detection"].output
            ).conflicts
        }
        missing_ids = {
            item.missing_requirement_id
            for item in MissingRequirementDetectionOutput.model_validate(
                context.results["missing_requirement_detection"].output
            ).missing_requirements
        }
        assumptions = FrameworkAssumptionLedgerResult.model_validate(
            context.results["assumption_ledger"].output
        )
        assumption_statuses = {
            item.assumption_id: item.status.value for item in assumptions.assumptions
        }
        chunk_map = {chunk.id: chunk for chunk in context.chunks}
        artifact_ids: list[str] = []
        for blueprint in output.requirement_blueprints:
            requirement = requirement_map[blueprint.requirement_id]
            if blueprint.requirement_title != requirement.title:
                raise ValueError("Blueprint requirement titles must match extraction.")
            for artifact in blueprint.artifacts:
                artifact_ids.append(artifact.artifact_id)
                cls._validate_artifact(
                    artifact,
                    requirement,
                    chunk_map,
                    ambiguity_ids,
                    conflict_ids,
                    missing_ids,
                    assumption_statuses,
                )
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("Engineering artifact IDs must be unique.")

    @classmethod
    def _validate_artifact(
        cls,
        artifact: BlueprintArtifact,
        requirement: object,
        chunk_map: dict[str, object],
        ambiguity_ids: set[str],
        conflict_ids: set[str],
        missing_ids: set[str],
        assumption_statuses: dict[str, str],
    ) -> None:
        expected_chunks = set(requirement.source_chunk_ids)
        if set(artifact.source_chunk_ids) != expected_chunks:
            raise ValueError(
                "Engineering artifact source chunks must exactly match the requirement."
            )
        expected_sections = {requirement.source_section}
        if set(artifact.source_sections) != expected_sections:
            raise ValueError(
                "Engineering artifact source sections must match the requirement."
            )
        if not expected_chunks.issubset(chunk_map):
            raise ValueError("Engineering artifact references unknown source chunks.")
        checks = (
            ("assumptions", artifact.related_assumption_ids, set(assumption_statuses)),
            ("ambiguities", artifact.related_ambiguity_ids, ambiguity_ids),
            ("conflicts", artifact.related_conflict_ids, conflict_ids),
            (
                "missing requirements",
                artifact.related_missing_requirement_ids,
                missing_ids,
            ),
        )
        for label, supplied, known in checks:
            unknown = set(supplied) - known
            if unknown:
                raise ValueError(
                    f"Engineering artifact references unknown {label}: "
                    + ", ".join(sorted(unknown))
                )
        if artifact.provenance is ArtifactProvenance.DOCUMENT_BACKED:
            source = cls._normalize(
                "\n".join(
                    getattr(chunk_map[chunk_id], "text")
                    for chunk_id in artifact.source_chunk_ids
                )
            )
            if cls._normalize(artifact.evidence_text or "") not in source:
                raise ValueError(
                    "Document-backed engineering evidence was not found in "
                    "the cited chunks."
                )
        if artifact.provenance is ArtifactProvenance.AI_ASSUMPTION:
            rejected = [
                item
                for item in artifact.related_assumption_ids
                if assumption_statuses[item] == "rejected"
            ]
            if rejected:
                raise ValueError(
                    "Engineering artifacts cannot depend on rejected assumptions."
                )
            if any(
                assumption_statuses[item] != "confirmed"
                for item in artifact.related_assumption_ids
            ) and artifact.artifact_type is not EngineeringArtifactType.OPEN_QUESTION:
                raise ValueError(
                    "Open assumptions cannot be used as settled engineering output."
                )

    @staticmethod
    def _ambiguity_ids(value: object) -> set[str]:
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        if not isinstance(value, dict):
            return set()
        return {
            str(issue["issue_id"])
            for assessment in value.get("assessments", [])
            if isinstance(assessment, dict)
            for issue in assessment.get("issues", [])
            if isinstance(issue, dict) and issue.get("issue_id")
        }

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip().casefold()
