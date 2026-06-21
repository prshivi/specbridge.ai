import hashlib
from statistics import fmean
from typing import Protocol

from openai import OpenAI

from app.agents.framework import AgentContext, AgentResult, BaseAgent
from app.models.conflict_detection import ConflictDetectionOutput
from app.models.knowledge import EntityType
from app.models.missing_requirements import (
    GapEvidenceOrigin,
    MissingRequirementDetectionOutput,
    MissingRequirementIssue,
)
from app.models.requirement_extraction import RequirementExtraction

SYSTEM_PROMPT = """You are the SpecBridge Missing Requirement Detection Agent.

You are a domain-agnostic analysis agent. Identify important requirement areas
that are absent or underdefined only when the supplied specification context
creates a reasonable need for them.

Potential gap categories include authentication, authorization, input
validation, error handling, edge cases, audit logging, notifications, retry
behavior, rate limiting, data retention, data privacy, security controls,
monitoring, performance, scalability, accessibility, localization, integration
failure handling, user roles, reporting, backup/recovery, admin operations,
configuration rules, and context-relevant compliance.

These categories are possibilities, not a mandatory checklist.

Contextual reasoning rules:
- Do not report a category merely because software could have it.
- Connect each gap to actual actors, workflows, integrations, requirements,
  constraints, conflicts, or ambiguity/missing-info flags.
- Authentication is relevant only when the context describes identities,
  protected access, sessions, accounts, or equivalent evidence.
- Integration failure handling is relevant only when an integration exists.
- Retention/privacy/compliance gaps require data, regulatory, contractual, or
  sensitivity context.
- Performance, scalability, observability, backup, accessibility,
  localization, reporting, rate limiting, and admin operations require
  contextual evidence that makes them material.
- Return an empty list when the specification is sufficient for its stated
  scope or when no contextual gap is supportable.

Output rules:
- Distinguish explicit_gap from inferred_gap.
- Use lower confidence and "potentially missing" language when uncertain.
- Preserve exact requirement and graph entity identifiers.
- Cite source chunks and sections when the contextual evidence comes from the
  document.
- Suggested requirement text is a draft for clarification, not a source fact.
- Ask one specific clarification question ending in "?".
- Do not invent domain-specific policies, limits, roles, regulations, or
  implementation choices.
- Do not implement assumptions, translation, architecture, or chatbot logic.
"""


class MissingRequirementProvider(Protocol):
    def detect(self, context: str) -> MissingRequirementDetectionOutput:
        """Detect contextual requirement gaps."""


class OpenAIMissingRequirementProvider:
    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def detect(self, context: str) -> MissingRequirementDetectionOutput:
        response = self._client.responses.parse(
            model=self._model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Identify only contextually supported requirement gaps "
                        f"from this specification evidence.\n\n{context}"
                    ),
                },
            ],
            text_format=MissingRequirementDetectionOutput,
        )
        if response.output_parsed is None:
            raise RuntimeError("The model returned no missing requirement output.")
        return response.output_parsed


class MissingRequirementDetectionAgent(BaseAgent):
    """Framework agent for contextual, non-checklist gap detection."""

    version = "1"

    def __init__(self, provider: MissingRequirementProvider | None = None) -> None:
        self._provider = provider

    @property
    def name(self) -> str:
        return "missing_requirement_detection"

    @property
    def description(self) -> str:
        return "Detects contextually relevant missing or underdefined requirements."

    def dependencies(self) -> tuple[str, ...]:
        return ("conflict_detection",)

    def validate(self, context: AgentContext) -> None:
        if not context.chunks:
            raise ValueError("Missing requirement detection requires document chunks.")
        if "requirement_extraction" not in context.results:
            raise ValueError("Missing requirement detection requires requirements.")
        if "conflict_detection" not in context.results:
            raise ValueError("Missing requirement detection requires conflict results.")
        provider = self._provider or context.llm_provider
        if provider is None or not hasattr(provider, "detect"):
            raise ValueError(
                "Missing requirement detection requires a gap detection provider."
            )

    def cache_fingerprint(self, context: AgentContext) -> str:
        fingerprint = context.configuration.get("source_fingerprint")
        if fingerprint:
            return str(fingerprint)
        payload = (
            context.dna_fingerprint
            + str(context.results["requirement_extraction"].output)
            + str(context.results["conflict_detection"].output)
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def execute(self, context: AgentContext) -> AgentResult:
        provider = self._provider or context.llm_provider
        output = provider.detect(self._assemble_context(context))
        self._validate_output(output, context)
        issues = output.missing_requirements
        return AgentResult(
            agent_name=self.name,
            output=output.model_dump(mode="json"),
            confidence=(
                fmean(issue.confidence for issue in issues) if issues else 0.0
            ),
            source_chunks=list(
                dict.fromkeys(
                    chunk_id
                    for issue in issues
                    for chunk_id in issue.source_chunk_ids
                )
            ),
            assumptions=[
                issue.missing_requirement_id
                for issue in issues
                if issue.explicit_gap_or_inferred_gap
                is GapEvidenceOrigin.INFERRED_GAP
            ],
            warnings=[
                f"{issue.missing_requirement_id} is a low-confidence potential gap."
                for issue in issues
                if issue.confidence < 0.6
            ],
        )

    @staticmethod
    def _assemble_context(context: AgentContext) -> str:
        requirements = RequirementExtraction.model_validate(
            context.results["requirement_extraction"].output
        )
        conflicts = ConflictDetectionOutput.model_validate(
            context.results["conflict_detection"].output
        )
        parts = [
            "SPECIFICATION_DNA:",
            (
                context.specification_dna.model_dump_json(indent=2)
                if hasattr(context.specification_dna, "model_dump_json")
                else str(context.specification_dna)
            ),
            "EXTRACTED_REQUIREMENTS:",
            requirements.model_dump_json(indent=2),
            "CONFLICTS:",
            conflicts.model_dump_json(indent=2),
        ]
        if context.knowledge_graph is not None:
            contextual_entities = [
                entity
                for entity in context.knowledge_graph.entities
                if entity.entity_type
                in {
                    EntityType.ACTOR,
                    EntityType.WORKFLOW,
                    EntityType.INTEGRATION,
                    EntityType.CONSTRAINT,
                    EntityType.BUSINESS_RULE,
                    EntityType.VALIDATION,
                    EntityType.PERMISSION,
                    EntityType.DATA_ENTITY,
                }
            ]
            parts.append(
                "KNOWLEDGE_GRAPH_CONTEXT:\n"
                + "\n".join(
                    (
                        f"{entity.entity_type.value}|{entity.id}|{entity.title}|"
                        f"{entity.description}|chunks={entity.source_chunk_ids}"
                    )
                    for entity in contextual_entities
                )
            )
        parts.append(
            "FLAGGED_REQUIREMENT_GAPS:\n"
            + "\n".join(
                (
                    f"{item.requirement_id}|ambiguity={item.ambiguity_flag}|"
                    f"missing_info={item.missing_info_flag}"
                )
                for item in requirements.requirements
                if item.ambiguity_flag or item.missing_info_flag
            )
        )
        return "\n\n".join(parts)

    @classmethod
    def _validate_output(
        cls,
        output: MissingRequirementDetectionOutput,
        context: AgentContext,
    ) -> None:
        requirements = RequirementExtraction.model_validate(
            context.results["requirement_extraction"].output
        ).requirements
        requirement_ids = {item.requirement_id for item in requirements}
        graph = context.knowledge_graph
        workflow_ids = cls._entity_identifiers(graph, EntityType.WORKFLOW)
        actor_ids = cls._entity_identifiers(graph, EntityType.ACTOR)
        issue_ids = [
            issue.missing_requirement_id for issue in output.missing_requirements
        ]
        if len(issue_ids) != len(set(issue_ids)):
            raise ValueError(
                "Missing requirement IDs must be unique within a document."
            )
        chunk_map = {chunk.id: chunk for chunk in context.chunks}
        for issue in output.missing_requirements:
            cls._validate_issue(
                issue,
                requirement_ids,
                workflow_ids,
                actor_ids,
                chunk_map,
            )

    @staticmethod
    def _entity_identifiers(
        graph: object,
        entity_type: EntityType,
    ) -> set[str]:
        if graph is None:
            return set()
        identifiers: set[str] = set()
        for entity in graph.entities:
            if entity.entity_type is not entity_type:
                continue
            identifiers.add(entity.id)
            identifiers.add(entity.title)
            for key in ("workflow_id", "actor_id", "explicit_id"):
                if entity.metadata.get(key):
                    identifiers.add(str(entity.metadata[key]))
        return identifiers

    @staticmethod
    def _validate_issue(
        issue: MissingRequirementIssue,
        requirement_ids: set[str],
        workflow_ids: set[str],
        actor_ids: set[str],
        chunk_map: dict[str, object],
    ) -> None:
        checks = (
            ("requirements", set(issue.related_requirement_ids), requirement_ids),
            ("workflows", set(issue.related_workflow_ids), workflow_ids),
            ("actors", set(issue.related_actor_ids), actor_ids),
        )
        for label, supplied, known in checks:
            unknown = supplied - known
            if unknown:
                raise ValueError(
                    f"Missing requirement issue references unknown {label}: "
                    + ", ".join(sorted(unknown))
                )
        unknown_chunks = set(issue.source_chunk_ids) - set(chunk_map)
        if unknown_chunks:
            raise ValueError(
                "Missing requirement issue references unknown source chunks: "
                + ", ".join(sorted(unknown_chunks))
            )
        allowed_sections = {
            getattr(chunk_map[chunk_id], "section")
            or getattr(chunk_map[chunk_id], "heading")
            or "unknown"
            for chunk_id in issue.source_chunk_ids
        }
        if not set(issue.source_sections).issubset(allowed_sections):
            raise ValueError(
                "Missing requirement source sections do not match source chunks."
            )
