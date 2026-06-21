from typing import Protocol

from openai import OpenAI

from app.models.assumptions import AssumptionLedger

SYSTEM_PROMPT = """You are the SpecBridge Assumption Ledger Agent.

Audit all supplied AI-generated outputs against the original source chunks.
Separate source-supported facts from assumptions.

A fact is a claim explicitly supported by the cited source chunk.
An assumption is a claim, classification, priority, interpretation, scope,
actor, rule, dependency, recommendation premise, or other detail that an AI
inferred but the specification did not explicitly state.

For every fact:
- use a unique ID such as FACT-001
- state the supported fact
- list every affected output reference
- cite exactly one supplied source chunk

For every assumption:
- use a unique ID such as ASM-001
- state the inference clearly
- explain why it is an inference rather than an explicit source fact
- assign confidence from 0.0 to 1.0
- list every affected output reference
- set needs_confirmation to true when downstream use could change scope,
  behavior, priority, policy, ownership, security, or delivery decisions
- cite the closest relevant supplied source chunk

Grounding rules:
- Do not invent new facts or assumptions.
- Audit only claims present in the supplied AI outputs.
- Do not convert explicitly stated source assumptions into AI assumptions;
  those are source facts about what the document assumes.
- Recommendations and stakeholder routing may contain assumptions; record the
  inferred premise, not merely the existence of a recommendation.
- A confidence score is not proof that an assumption is factual.
- Keep facts and assumptions in separate arrays.
- Use only supplied output references and source chunk IDs.
- If every audited claim is explicit, return an empty assumptions list.
"""


class AssumptionModelProvider(Protocol):
    """Provider boundary for structured provenance auditing."""

    def analyze(self, context: str) -> AssumptionLedger:
        """Separate output facts from inferred assumptions."""


class OpenAIAssumptionProvider:
    """OpenAI Responses API implementation using structured output."""

    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def analyze(self, context: str) -> AssumptionLedger:
        response = self._client.responses.parse(
            model=self._model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Audit these AI outputs against the supplied source chunks "
                        f"and build the assumption ledger.\n\n{context}"
                    ),
                },
            ],
            text_format=AssumptionLedger,
        )
        if response.output_parsed is None:
            raise RuntimeError("The model returned no assumption ledger.")
        return response.output_parsed
