import hashlib
import re
from statistics import fmean
from typing import Protocol

from openai import OpenAI

from app.agents.framework import AgentContext, AgentResult, BaseAgent
from app.models.assumption_ledger import (
    AssumptionLedgerOutput,
    AssumptionStatus,
    LedgerAssumption,
    LedgerFact,
)
from app.models.conflict_detection import ConflictDetectionOutput
from app.models.missing_requirements import MissingRequirementDetectionOutput
from app.models.requirement_extraction import RequirementExtraction

SYSTEM_PROMPT = """You are the SpecBridge Assumption Ledger Agent.

Create a domain-agnostic ledger that strictly separates specification-backed
facts from AI-inferred assumptions.

Facts:
- Include only statements directly supported by verbatim document evidence.
- Cite exact source chunks and sections.

Assumptions:
- Explicitly label every inference as an assumption.
- Create an assumption only when missing or underdefined information requires
  a provisional interpretation, or when a prior ambiguity, conflict, or missing
  requirement implies that a decision will be needed later.
- Do not turn fully supported document statements into assumptions.
- Explain why the inference exists and cite related requirement, ambiguity,
  conflict, or missing-requirement IDs.
- Never invent domain policy, limits, roles, validations, error behavior,
  integration behavior, data flow, permissions, notifications, or workflows.
- Use lower confidence when evidence is indirect.
- Every generated assumption must have status "open".
- Ask one specific confirmation question ending in "?".
- Return an empty assumption list when no inference is supportable.

The evidence_text must be either verbatim text from cited source chunks or the
exact description/reason of a cited analysis issue. Do not generate APIs,
architecture, implementation tasks, or translated requirements.
"""


class AssumptionLedgerProvider(Protocol):
    def audit(self, context: str) -> AssumptionLedgerOutput:
        """Separate source facts from contextual assumptions."""


class OpenAIAssumptionLedgerProvider:
    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def audit(self, context: str) -> AssumptionLedgerOutput:
        response = self._client.responses.parse(
            model=self._model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Build the fact and assumption ledger from this "
                        f"evidence.\n\n{context}"
                    ),
                },
            ],
            text_format=AssumptionLedgerOutput,
        )
        if response.output_parsed is None:
            raise RuntimeError("The model returned no assumption ledger output.")
        return response.output_parsed


class AssumptionLedgerAgent(BaseAgent):
    """Framework analysis agent that keeps facts and inferences distinct."""

    version = "1"

    def __init__(self, provider: AssumptionLedgerProvider | None = None) -> None:
        self._provider = provider

    @property
    def name(self) -> str:
        return "assumption_ledger"

    @property
    def description(self) -> str:
        return "Separates document-backed facts from stakeholder assumptions."

    def dependencies(self) -> tuple[str, ...]:
        return ("missing_requirement_detection",)

    def validate(self, context: AgentContext) -> None:
        if not context.chunks:
            raise ValueError("Assumption ledger requires document chunks.")
        for dependency in (
            "requirement_extraction",
            "ambiguity_detection",
            "conflict_detection",
            "missing_requirement_detection",
        ):
            if dependency not in context.results:
                raise ValueError(f"Assumption ledger requires {dependency} results.")
        provider = self._provider or context.llm_provider
        if provider is None or not hasattr(provider, "audit"):
            raise ValueError("Assumption ledger requires an audit provider.")

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
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def execute(self, context: AgentContext) -> AgentResult:
        provider = self._provider or context.llm_provider
        output = provider.audit(self._assemble_context(context))
        self._validate_output(output, context)
        assumptions = output.assumptions
        return AgentResult(
            agent_name=self.name,
            output=output.model_dump(mode="json"),
            confidence=(
                fmean(item.confidence for item in assumptions)
                if assumptions
                else 1.0
            ),
            source_chunks=list(
                dict.fromkeys(
                    chunk_id
                    for item in [*output.facts, *assumptions]
                    for chunk_id in item.source_chunk_ids
                )
            ),
            assumptions=[item.assumption_id for item in assumptions],
            warnings=[
                f"{item.assumption_id} is a high-risk open assumption."
                for item in assumptions
                if item.risk_level.value in {"high", "critical"}
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
        missing = MissingRequirementDetectionOutput.model_validate(
            context.results["missing_requirement_detection"].output
        )
        ambiguity = context.results["ambiguity_detection"].output
        parts = [
            "SPECIFICATION_DNA:",
            (
                context.specification_dna.model_dump_json(indent=2)
                if hasattr(context.specification_dna, "model_dump_json")
                else str(context.specification_dna)
            ),
            "REQUIREMENTS:",
            requirements.model_dump_json(indent=2),
            "AMBIGUITIES:",
            str(ambiguity),
            "CONFLICTS:",
            conflicts.model_dump_json(indent=2),
            "MISSING_REQUIREMENTS:",
            missing.model_dump_json(indent=2),
            "SOURCE_CHUNKS:",
            "\n".join(
                (
                    f"{chunk.id}|section={chunk.section or chunk.heading or 'unknown'}"
                    f"|{chunk.text}"
                )
                for chunk in context.chunks
            ),
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
    def _validate_output(
        cls,
        output: AssumptionLedgerOutput,
        context: AgentContext,
    ) -> None:
        fact_ids = [item.fact_id for item in output.facts]
        assumption_ids = [item.assumption_id for item in output.assumptions]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("Fact IDs must be unique within a document.")
        if len(assumption_ids) != len(set(assumption_ids)):
            raise ValueError("Assumption IDs must be unique within a document.")

        requirements = RequirementExtraction.model_validate(
            context.results["requirement_extraction"].output
        )
        conflicts = ConflictDetectionOutput.model_validate(
            context.results["conflict_detection"].output
        )
        missing = MissingRequirementDetectionOutput.model_validate(
            context.results["missing_requirement_detection"].output
        )
        ambiguity_issues = cls._ambiguity_issues(
            context.results["ambiguity_detection"].output
        )
        known_ids = {
            "requirements": {
                item.requirement_id: item.description
                for item in requirements.requirements
            },
            "ambiguities": {
                str(item["issue_id"]): str(item.get("reason", ""))
                for item in ambiguity_issues
                if item.get("issue_id")
            },
            "conflicts": {
                item.conflict_id: item.description for item in conflicts.conflicts
            },
            "missing": {
                item.missing_requirement_id: item.description
                for item in missing.missing_requirements
            },
        }
        chunk_map = {chunk.id: chunk for chunk in context.chunks}
        for fact in output.facts:
            cls._validate_fact(fact, chunk_map, known_ids["requirements"])
        for assumption in output.assumptions:
            cls._validate_assumption(assumption, chunk_map, known_ids)

        fact_claims = {
            cls._normalize(value)
            for item in output.facts
            for value in (item.title, item.description, item.evidence_text)
        }
        for assumption in output.assumptions:
            if cls._normalize(assumption.description) in fact_claims:
                raise ValueError(
                    "A document-backed fact cannot also be stored as an assumption."
                )

    @classmethod
    def _validate_fact(
        cls,
        fact: LedgerFact,
        chunk_map: dict[str, object],
        requirement_descriptions: dict[str, str],
    ) -> None:
        cls._validate_chunks_and_sections(
            fact.source_chunk_ids,
            fact.source_sections,
            chunk_map,
        )
        unknown = set(fact.related_requirement_ids) - set(
            requirement_descriptions
        )
        if unknown:
            raise ValueError(
                "Fact references unknown requirements: "
                + ", ".join(sorted(unknown))
            )
        cls._validate_chunk_evidence(
            fact.evidence_text,
            fact.source_chunk_ids,
            chunk_map,
        )

    @classmethod
    def _validate_assumption(
        cls,
        assumption: LedgerAssumption,
        chunk_map: dict[str, object],
        known_ids: dict[str, dict[str, str]],
    ) -> None:
        if assumption.status is not AssumptionStatus.OPEN:
            raise ValueError("Newly generated assumptions must have open status.")
        cls._validate_chunks_and_sections(
            assumption.source_chunk_ids,
            assumption.source_sections,
            chunk_map,
        )
        references = (
            ("requirements", assumption.related_requirement_ids),
            ("ambiguities", assumption.related_ambiguity_ids),
            ("conflicts", assumption.related_conflict_ids),
            ("missing", assumption.related_missing_requirement_ids),
        )
        related_evidence: list[str] = []
        for label, supplied in references:
            unknown = set(supplied) - set(known_ids[label])
            if unknown:
                raise ValueError(
                    f"Assumption references unknown {label}: "
                    + ", ".join(sorted(unknown))
                )
            related_evidence.extend(known_ids[label][item] for item in supplied)
        if assumption.source_chunk_ids:
            cls._validate_chunk_evidence(
                assumption.evidence_text,
                assumption.source_chunk_ids,
                chunk_map,
            )
        elif cls._normalize(assumption.evidence_text) not in {
            cls._normalize(value) for value in related_evidence
        }:
            raise ValueError(
                "Assumption evidence must match a cited analysis issue when "
                "source chunks are not supplied."
            )

    @staticmethod
    def _validate_chunks_and_sections(
        chunk_ids: list[str],
        sections: list[str],
        chunk_map: dict[str, object],
    ) -> None:
        unknown = set(chunk_ids) - set(chunk_map)
        if unknown:
            raise ValueError(
                "Ledger item references unknown source chunks: "
                + ", ".join(sorted(unknown))
            )
        allowed_sections = {
            getattr(chunk_map[chunk_id], "section")
            or getattr(chunk_map[chunk_id], "heading")
            or "unknown"
            for chunk_id in chunk_ids
        }
        if not set(sections).issubset(allowed_sections):
            raise ValueError("Ledger source sections do not match source chunks.")

    @classmethod
    def _validate_chunk_evidence(
        cls,
        evidence: str,
        chunk_ids: list[str],
        chunk_map: dict[str, object],
    ) -> None:
        source = cls._normalize(
            "\n".join(getattr(chunk_map[chunk_id], "text") for chunk_id in chunk_ids)
        )
        if cls._normalize(evidence) not in source:
            raise ValueError("Ledger evidence was not found in cited source chunks.")

    @staticmethod
    def _ambiguity_issues(value: object) -> list[dict[str, object]]:
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        if not isinstance(value, dict):
            return []
        issues: list[dict[str, object]] = []
        for assessment in value.get("assessments", []):
            if isinstance(assessment, dict):
                issues.extend(
                    item
                    for item in assessment.get("issues", [])
                    if isinstance(item, dict)
                )
        return issues

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip().casefold()
