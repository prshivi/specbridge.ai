import hashlib
import re
from statistics import fmean
from typing import Protocol

from openai import OpenAI

from app.agents.framework import AgentContext, AgentResult, BaseAgent
from app.models.conflict_detection import (
    ConflictDetectionOutput,
    DetectedConflict,
)
from app.models.knowledge import EntityType
from app.models.requirement_extraction import RequirementExtraction

SYSTEM_PROMPT = """You are the SpecBridge Conflict Detection Agent.

You are a domain-agnostic analysis agent. Analyze the complete set of extracted
requirements, business rules, validations, permissions, integrations, workflows,
constraints, data rules, non-functional requirements, and acceptance conditions.

Detect only evidence-supported conflicts:
- requirement_vs_requirement
- business_rule_vs_business_rule
- requirement_vs_validation
- permission_access
- workflow_sequence
- integration_behavior
- data_rule
- non_functional
- overlap_different_meaning
- acceptance_condition

A conflict exists when supplied statements cannot all be applied under the same
scope or when overlapping statements assign materially different behavior.

For every conflict:
- use a unique conflict ID
- identify every involved requirement and business-rule ID
- provide at least two verbatim evidence texts
- cite exact source chunk IDs and sections
- explain why the contradiction matters
- ask one specific resolution question ending in "?"
- recommend one stakeholder from business, product, architect, backend,
  frontend, security, QA, or DevOps
- mark whether development is blocked

Grounding rules:
- Do not invent conflicts, policies, scopes, exceptions, actors, sequences,
  integrations, data behavior, quality targets, or acceptance conditions.
- Missing detail alone is not a conflict.
- Similar or duplicate requirements are not conflicts unless their meanings
  materially differ.
- A general rule and an explicitly scoped exception are not a conflict.
- Different actors, regions, products, states, or time periods are not a
  conflict unless their stated scopes overlap.
- If evidence is plausible but uncertain, use low confidence and ask for
  clarification.
- Return an empty list when no conflict is supported.
- Do not perform ambiguity analysis, requirement generation, translation,
  architecture, or implementation design.
"""


class FrameworkConflictProvider(Protocol):
    def detect(self, context: str) -> ConflictDetectionOutput:
        """Detect grounded conflicts from framework context."""


class OpenAIFrameworkConflictProvider:
    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def detect(self, context: str) -> ConflictDetectionOutput:
        response = self._client.responses.parse(
            model=self._model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Detect only supported contradictions in this complete "
                        f"specification context.\n\n{context}"
                    ),
                },
            ],
            text_format=ConflictDetectionOutput,
        )
        if response.output_parsed is None:
            raise RuntimeError("The model returned no conflict detection output.")
        return response.output_parsed


class ConflictDetectionAgent(BaseAgent):
    """Framework analysis agent for cross-requirement contradictions."""

    version = "1"

    def __init__(self, provider: FrameworkConflictProvider | None = None) -> None:
        self._provider = provider

    @property
    def name(self) -> str:
        return "conflict_detection"

    @property
    def description(self) -> str:
        return "Detects evidence-grounded conflicts before development."

    def dependencies(self) -> tuple[str, ...]:
        return ("requirement_extraction",)

    def validate(self, context: AgentContext) -> None:
        if not context.chunks:
            raise ValueError("Conflict detection requires document chunks.")
        dependency = context.results.get("requirement_extraction")
        if dependency is None:
            raise ValueError("Conflict detection requires extracted requirements.")
        provider = self._provider or context.llm_provider
        if provider is None or not hasattr(provider, "detect"):
            raise ValueError("Conflict detection requires a conflict provider.")

    def cache_fingerprint(self, context: AgentContext) -> str:
        fingerprint = context.configuration.get("source_fingerprint")
        if fingerprint:
            return str(fingerprint)
        payload = context.dna_fingerprint + str(
            context.results["requirement_extraction"].output
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def execute(self, context: AgentContext) -> AgentResult:
        provider = self._provider or context.llm_provider
        output = provider.detect(self._assemble_context(context))
        self._validate_output(output, context)
        conflicts = output.conflicts
        return AgentResult(
            agent_name=self.name,
            output=output.model_dump(mode="json"),
            confidence=(
                fmean(conflict.confidence for conflict in conflicts)
                if conflicts
                else 0.0
            ),
            source_chunks=list(
                dict.fromkeys(
                    chunk_id
                    for conflict in conflicts
                    for chunk_id in conflict.source_chunk_ids
                )
            ),
            warnings=[
                f"{conflict.conflict_id} has low confidence."
                for conflict in conflicts
                if conflict.confidence < 0.6
            ],
        )

    @staticmethod
    def _assemble_context(context: AgentContext) -> str:
        requirements = RequirementExtraction.model_validate(
            context.results["requirement_extraction"].output
        )
        parts = [
            "SPECIFICATION_DNA:",
            (
                context.specification_dna.model_dump_json(indent=2)
                if hasattr(context.specification_dna, "model_dump_json")
                else str(context.specification_dna)
            ),
            f"TOTAL_REQUIREMENTS: {len(requirements.requirements)}",
        ]
        for requirement in requirements.requirements:
            parts.append(
                "\n".join(
                    [
                        f"--- REQUIREMENT {requirement.requirement_id} ---",
                        f"TITLE: {requirement.title}",
                        f"CATEGORY: {requirement.category.value}",
                        f"DESCRIPTION: {requirement.description}",
                        f"EVIDENCE: {requirement.evidence_text}",
                        f"SOURCE_CHUNKS: {', '.join(requirement.source_chunk_ids)}",
                        f"SOURCE_SECTION: {requirement.source_section}",
                    ]
                )
            )
        if context.knowledge_graph is not None:
            rules = [
                entity
                for entity in context.knowledge_graph.entities
                if entity.entity_type is EntityType.BUSINESS_RULE
            ]
            parts.append(f"TOTAL_GRAPH_BUSINESS_RULES: {len(rules)}")
            for rule in rules:
                rule_id = str(rule.metadata.get("explicit_id") or rule.title)
                parts.append(
                    "\n".join(
                        [
                            f"--- BUSINESS_RULE {rule_id} ---",
                            f"DESCRIPTION: {rule.description}",
                            f"SOURCE_CHUNKS: {', '.join(rule.source_chunk_ids)}",
                        ]
                    )
                )
        return "\n\n".join(parts)

    @classmethod
    def _validate_output(
        cls,
        output: ConflictDetectionOutput,
        context: AgentContext,
    ) -> None:
        requirements = RequirementExtraction.model_validate(
            context.results["requirement_extraction"].output
        ).requirements
        requirement_ids = {item.requirement_id for item in requirements}
        business_rule_ids = {
            item.requirement_id
            for item in requirements
            if item.category.value == "business_rule"
        }
        if context.knowledge_graph is not None:
            business_rule_ids.update(
                str(entity.metadata.get("explicit_id") or entity.title)
                for entity in context.knowledge_graph.entities
                if entity.entity_type is EntityType.BUSINESS_RULE
            )
        conflict_ids = [conflict.conflict_id for conflict in output.conflicts]
        if len(conflict_ids) != len(set(conflict_ids)):
            raise ValueError("Conflict IDs must be unique within a document.")
        chunk_map = {chunk.id: chunk for chunk in context.chunks}
        for conflict in output.conflicts:
            cls._validate_conflict(
                conflict,
                requirement_ids,
                business_rule_ids,
                chunk_map,
            )

    @staticmethod
    def _validate_conflict(
        conflict: DetectedConflict,
        requirement_ids: set[str],
        business_rule_ids: set[str],
        chunk_map: dict[str, object],
    ) -> None:
        unknown_requirements = (
            set(conflict.involved_requirement_ids) - requirement_ids
        )
        if unknown_requirements:
            raise ValueError(
                "Conflict references unknown requirements: "
                + ", ".join(sorted(unknown_requirements))
            )
        unknown_rules = (
            set(conflict.involved_business_rule_ids) - business_rule_ids
        )
        if unknown_rules:
            raise ValueError(
                "Conflict references unknown business rules: "
                + ", ".join(sorted(unknown_rules))
            )
        unknown_chunks = set(conflict.source_chunk_ids) - set(chunk_map)
        if unknown_chunks:
            raise ValueError(
                "Conflict references unknown source chunks: "
                + ", ".join(sorted(unknown_chunks))
            )
        allowed_sections = {
            getattr(chunk_map[chunk_id], "section")
            or getattr(chunk_map[chunk_id], "heading")
            or "unknown"
            for chunk_id in conflict.source_chunk_ids
        }
        if not set(conflict.source_sections).issubset(allowed_sections):
            raise ValueError("Conflict source sections do not match source chunks.")
        source_text = ConflictDetectionAgent._normalize(
            "\n".join(
                getattr(chunk_map[chunk_id], "text")
                for chunk_id in conflict.source_chunk_ids
            )
        )
        for evidence in conflict.evidence_texts:
            if ConflictDetectionAgent._normalize(evidence) not in source_text:
                raise ValueError(
                    f"Conflict {conflict.conflict_id} evidence was not found "
                    "in its cited source chunks."
                )

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip().casefold()
