import hashlib
import re
from statistics import fmean
from typing import Protocol

from openai import OpenAI

from app.agents.framework import AgentContext, AgentResult, BaseAgent
from app.models.requirement_extraction import (
    RequirementExtraction,
    ExtractedRequirement,
)

SYSTEM_PROMPT = """You are the SpecBridge Requirement Extraction Agent.

You are a domain-agnostic analysis agent. Extract structured software
requirements from the complete uploaded specification and its Specification DNA.

Classify only:
- functional
- non_functional
- business_rule
- validation_rule
- permission_access
- integration
- data
- reporting_analytics
- notification
- compliance_security

For every requirement return:
- a unique requirement_id
- concise title and description
- exactly one supported category
- priority only when explicitly stated; otherwise "unspecified"
- confidence from 0.0 to 1.0
- exact source chunk IDs
- one exact source section
- evidence_text copied verbatim from the cited chunks
- explicit_or_inferred
- ambiguity_flag
- missing_info_flag

Grounding rules:
- Extract only behavior, quality attributes, rules, access controls,
  integrations, data expectations, reporting, notifications, or
  compliance/security statements supported by the supplied evidence.
- Do not invent requirements.
- An inferred requirement must be a close implication of cited evidence, must
  retain verbatim evidence_text, and must be marked inferred.
- If confidence is below 0.6, ambiguity_flag must be true.
- Mark missing_info_flag only when the extracted requirement itself depends on
  a missing detail visible in the cited evidence.
- Preserve explicit source requirement IDs when present.
- Generate stable category-prefixed IDs only when no explicit ID exists.
- Split compound statements only when each resulting requirement is supported.
- Do not hardcode or assume any industry behavior.
- Do not generate APIs, user stories, architecture, implementation tasks,
  ambiguity analysis, conflict analysis, or technical designs.
- Return an empty requirements list when the document contains no supported
  software requirements.
"""


class RequirementExtractionProvider(Protocol):
    def extract(self, context: str) -> RequirementExtraction:
        """Extract domain-agnostic requirements from grounded context."""


class OpenAIRequirementExtractionProvider:
    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def extract(self, context: str) -> RequirementExtraction:
        response = self._client.responses.parse(
            model=self._model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Extract only supported requirements from this complete "
                        f"evidence context.\n\n{context}"
                    ),
                },
            ],
            text_format=RequirementExtraction,
        )
        if response.output_parsed is None:
            raise RuntimeError("The model returned no requirement extraction.")
        return response.output_parsed


class RequirementExtractionAgent(BaseAgent):
    """Production framework agent for domain-agnostic requirement extraction."""

    version = "1"

    def __init__(
        self,
        provider: RequirementExtractionProvider | None = None,
    ) -> None:
        self._provider = provider

    @property
    def name(self) -> str:
        return "requirement_extraction"

    @property
    def description(self) -> str:
        return "Extracts traceable, classified software requirements."

    def dependencies(self) -> tuple[str, ...]:
        return ("specification_understanding",)

    def validate(self, context: AgentContext) -> None:
        if not context.chunks:
            raise ValueError("Requirement extraction requires document chunks.")
        if not context.specification_dna:
            raise ValueError("Requirement extraction requires Specification DNA.")
        provider = self._provider or context.llm_provider
        if provider is None or not hasattr(provider, "extract"):
            raise ValueError(
                "Requirement extraction requires a requirement extraction provider."
            )

    def cache_fingerprint(self, context: AgentContext) -> str:
        source_fingerprint = context.configuration.get("source_fingerprint")
        if source_fingerprint:
            return str(source_fingerprint)
        payload = context.dna_fingerprint + "\n" + "\n".join(
            f"{chunk.id}|{chunk.section}|{chunk.text}" for chunk in context.chunks
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def execute(self, context: AgentContext) -> AgentResult:
        provider = self._provider or context.llm_provider
        extraction = provider.extract(self._assemble_context(context))
        self._validate_extraction(extraction, context)
        requirements = extraction.requirements
        return AgentResult(
            agent_name=self.name,
            output=extraction.model_dump(mode="json"),
            confidence=(
                fmean(requirement.confidence for requirement in requirements)
                if requirements
                else 0.0
            ),
            source_chunks=list(
                dict.fromkeys(
                    chunk_id
                    for requirement in requirements
                    for chunk_id in requirement.source_chunk_ids
                )
            ),
            assumptions=[
                requirement.requirement_id
                for requirement in requirements
                if requirement.explicit_or_inferred.value == "inferred"
            ],
            warnings=[
                f"{requirement.requirement_id} requires clarification."
                for requirement in requirements
                if requirement.ambiguity_flag or requirement.missing_info_flag
            ],
        )

    @staticmethod
    def _assemble_context(context: AgentContext) -> str:
        dna = (
            context.specification_dna.model_dump_json(indent=2)
            if hasattr(context.specification_dna, "model_dump_json")
            else str(context.specification_dna)
        )
        parts = [
            "SPECIFICATION_DNA:",
            dna,
            f"TOTAL_SOURCE_CHUNKS: {len(context.chunks)}",
        ]
        for chunk in context.chunks:
            parts.append(
                "\n".join(
                    [
                        f"--- SOURCE_CHUNK {chunk.id} ---",
                        f"CHUNK_NUMBER: {chunk.chunk_number}",
                        f"TYPE: {chunk.chunk_type.value}",
                        f"PAGE: {chunk.page or 'unknown'}",
                        f"SECTION: {chunk.section or chunk.heading or 'unknown'}",
                        f"HEADING: {chunk.heading or 'unknown'}",
                        "CONTENT:",
                        chunk.text,
                    ]
                )
            )
        return "\n\n".join(parts)

    @classmethod
    def _validate_extraction(
        cls,
        extraction: RequirementExtraction,
        context: AgentContext,
    ) -> None:
        chunk_map = {chunk.id: chunk for chunk in context.chunks}
        ids = [item.requirement_id for item in extraction.requirements]
        if len(ids) != len(set(ids)):
            raise ValueError("Requirement IDs must be unique within a document.")
        for requirement in extraction.requirements:
            cls._validate_requirement(requirement, chunk_map)

    @staticmethod
    def _validate_requirement(
        requirement: ExtractedRequirement,
        chunk_map: dict[str, object],
    ) -> None:
        unknown = set(requirement.source_chunk_ids) - set(chunk_map)
        if unknown:
            raise ValueError(
                "Requirements cite unknown source chunks: "
                + ", ".join(sorted(unknown))
            )
        allowed_sections = {
            getattr(chunk_map[chunk_id], "section")
            or getattr(chunk_map[chunk_id], "heading")
            or "unknown"
            for chunk_id in requirement.source_chunk_ids
        }
        if requirement.source_section not in allowed_sections:
            raise ValueError(
                f"Requirement {requirement.requirement_id} cites source section "
                "that does not match its source chunks."
            )
        evidence = RequirementExtractionAgent._normalize_text(
            requirement.evidence_text
        )
        source_text = RequirementExtractionAgent._normalize_text(
            "\n".join(
                getattr(chunk_map[chunk_id], "text")
                for chunk_id in requirement.source_chunk_ids
            )
        )
        if evidence not in source_text:
            raise ValueError(
                f"Requirement {requirement.requirement_id} evidence_text was not "
                "found in its cited source chunks."
            )

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip().casefold()
