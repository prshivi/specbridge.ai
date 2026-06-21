from typing import Protocol

from openai import OpenAI

from app.models.copilot import CopilotAnswer

SYSTEM_PROMPT = """You are the SpecBridge Developer Copilot.

Answer the developer's question using only these supplied sources:
1. Original specification chunks
2. Stored requirements, including business rules
3. Stored architecture recommendations

Do not use the specification understanding summary, assumption ledger,
ambiguity findings, conflict findings, engineering translation, general
knowledge, framework conventions, or unstated implementation assumptions.

Answer rules:
- Every factual claim must be supported by one or more supplied source chunks.
- Cite source chunk IDs in the structured citations.
- Requirement IDs and architecture recommendation IDs may be added to citations
  only when they are supplied and relevant.
- Never invent behavior, fields, APIs, database details, actors, integrations,
  security rules, error handling, or architecture.
- Architecture recommendations are recommendations, not source facts; describe
  them as recommended.
- If the allowed sources do not fully support an answer, return:
  answer = "Not enough information."
  available = false
  no citations
  one specific clarification question.
- Do not provide a partial speculative answer before the fallback.
"""


class CopilotModelProvider(Protocol):
    """Provider boundary for grounded developer Q&A."""

    def answer(self, context: str) -> CopilotAnswer:
        """Answer from the allowed grounded context."""


class OpenAICopilotProvider:
    """OpenAI Responses API implementation using structured output."""

    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def answer(self, context: str) -> CopilotAnswer:
        response = self._client.responses.parse(
            model=self._model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Answer this developer question using only the allowed "
                        f"sources in the context.\n\n{context}"
                    ),
                },
            ],
            text_format=CopilotAnswer,
        )
        if response.output_parsed is None:
            raise RuntimeError("The model returned no copilot answer.")
        return response.output_parsed
