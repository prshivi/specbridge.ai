import hashlib
from statistics import fmean
from typing import Protocol

from openai import OpenAI

from app.agents.framework import AgentContext, AgentResult, BaseAgent
from app.models.specification_dna import EvidenceBase, SpecificationDNA

SYSTEM_PROMPT = """You are the SpecBridge Specification Understanding Agent.

Your only task is to extract an evidence-grounded Specification DNA from the
complete uploaded specification.

Extract:
- project name
- project summary
- business objectives
- actors
- user personas
- modules
- workflows
- integrations
- business rules
- constraints
- assumptions explicitly stated by the source
- glossary entries
- key terminology

Evidence rules:
- Every returned item must cite one or more exact SOURCE_CHUNK_ID values.
- Every returned item must cite the corresponding SECTION values exactly as supplied.
- Confidence measures extraction certainty, not business correctness.
- Use null for an unsupported singular field and [] for unsupported collections.
- Do not infer missing project names, actors, personas, modules, workflows,
  integrations, rules, constraints, assumptions, glossary entries, or terminology.
- Do not convert normal statements into assumptions; include assumptions only
  when the source explicitly labels or states them as assumptions.
- User personas require explicit persona or user-profile evidence. An actor is
  not automatically a persona.
- Key terminology must be domain-significant and explicitly used or defined.

Scope rules:
- Do not generate APIs or endpoint designs.
- Do not generate user stories.
- Do not generate architecture or technology recommendations.
- Do not generate requirements, implementation tasks, or acceptance criteria.
- Do not add general knowledge.
- Preserve source terminology.
"""


class SpecificationDNAProvider(Protocol):
    def extract(self, context: str) -> SpecificationDNA:
        """Extract structured Specification DNA from grounded context."""


class OpenAISpecificationDNAProvider:
    """OpenAI Responses API provider for structured Specification DNA."""

    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def extract(self, context: str) -> SpecificationDNA:
        response = self._client.responses.parse(
            model=self._model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Extract only the supported Specification DNA from this "
                        f"complete evidence context.\n\n{context}"
                    ),
                },
            ],
            text_format=SpecificationDNA,
        )
        if response.output_parsed is None:
            raise RuntimeError("The model returned no Specification DNA.")
        return response.output_parsed


class SpecificationUnderstandingAgent(BaseAgent):
    """First production framework agent: whole-specification understanding."""

    version = "2"

    def __init__(self, provider: SpecificationDNAProvider | None = None) -> None:
        self._provider = provider

    @property
    def name(self) -> str:
        return "specification_understanding"

    @property
    def description(self) -> str:
        return "Extracts evidence-grounded Specification DNA."

    def validate(self, context: AgentContext) -> None:
        if not context.chunks:
            raise ValueError("Specification understanding requires document chunks.")
        provider = self._provider or context.llm_provider
        if provider is None or not hasattr(provider, "extract"):
            raise ValueError(
                "Specification understanding requires a Specification DNA provider."
            )

    def dependencies(self) -> tuple[str, ...]:
        return ()

    def cache_fingerprint(self, context: AgentContext) -> str:
        source_fingerprint = context.configuration.get("source_fingerprint")
        if source_fingerprint:
            return str(source_fingerprint)
        payload = "\n".join(
            f"{chunk.id}|{chunk.section}|{chunk.heading}|{chunk.text}"
            for chunk in context.chunks
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def execute(self, context: AgentContext) -> AgentResult:
        provider = self._provider or context.llm_provider
        dna = provider.extract(self._assemble_context(context))
        self._validate_evidence(dna, context)
        context.specification_dna = dna
        items = list(self._evidence_items(dna))
        return AgentResult(
            agent_name=self.name,
            output=dna.model_dump(mode="json"),
            confidence=fmean(item.confidence for item in items) if items else 0.0,
            source_chunks=list(
                dict.fromkeys(
                    chunk_id
                    for item in items
                    for chunk_id in item.source_chunk_ids
                )
            ),
            assumptions=[],
            warnings=[],
        )

    @staticmethod
    def _assemble_context(context: AgentContext) -> str:
        parts = [f"TOTAL_CHUNKS: {len(context.chunks)}"]
        if context.knowledge_graph is not None:
            parts.append(
                "KNOWLEDGE_GRAPH_ENTITIES: "
                f"{len(context.knowledge_graph.entities)}"
            )
        for chunk in context.chunks:
            parts.append(
                "\n".join(
                    [
                        f"--- CHUNK {chunk.chunk_number} ---",
                        f"SOURCE_CHUNK_ID: {chunk.id}",
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
    def _validate_evidence(
        cls,
        dna: SpecificationDNA,
        context: AgentContext,
    ) -> None:
        chunk_map = {chunk.id: chunk for chunk in context.chunks}
        for item in cls._evidence_items(dna):
            unknown = set(item.source_chunk_ids) - set(chunk_map)
            if unknown:
                raise ValueError(
                    "Specification DNA cites unknown source chunks: "
                    + ", ".join(sorted(unknown))
                )
            allowed_sections = {
                chunk_map[chunk_id].section
                or chunk_map[chunk_id].heading
                or "unknown"
                for chunk_id in item.source_chunk_ids
            }
            invalid_sections = (
                set(item.source_document_sections) - allowed_sections
            )
            if invalid_sections:
                raise ValueError(
                    "Specification DNA cites sections that do not match its "
                    "source chunks: "
                    + ", ".join(sorted(invalid_sections))
                )
        for collection_name in (
            "actors",
            "user_personas",
            "modules",
            "workflows",
            "integrations",
        ):
            values = getattr(dna, collection_name)
            names = [value.name.casefold() for value in values]
            if len(names) != len(set(names)):
                raise ValueError(
                    f"Specification DNA contains duplicate {collection_name}."
                )
        for collection_name in ("glossary", "key_terminology"):
            values = getattr(dna, collection_name)
            terms = [value.term.casefold() for value in values]
            if len(terms) != len(set(terms)):
                raise ValueError(
                    f"Specification DNA contains duplicate {collection_name}."
                )

    @staticmethod
    def _evidence_items(dna: SpecificationDNA) -> list[EvidenceBase]:
        items: list[EvidenceBase] = []
        if dna.project_name is not None:
            items.append(dna.project_name)
        if dna.project_summary is not None:
            items.append(dna.project_summary)
        for field_name in (
            "business_objectives",
            "actors",
            "user_personas",
            "modules",
            "workflows",
            "integrations",
            "business_rules",
            "constraints",
            "explicit_assumptions",
            "glossary",
            "key_terminology",
        ):
            items.extend(getattr(dna, field_name))
        return items
