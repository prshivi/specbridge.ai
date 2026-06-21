from typing import Protocol

from openai import OpenAI

from app.models.ambiguity import AmbiguityAnalysis

SYSTEM_PROMPT = """You are the SpecBridge Ambiguity Detection Agent.

Analyze every supplied requirement. Return one assessment for every requirement,
including an empty issues list when the requirement is sufficiently explicit.

Detect only:
- vague or subjective language
- missing or unclear actors
- missing validation behavior
- referenced but undefined business rules
- missing material edge cases
- missing error or failure handling
- referenced but undefined integrations

For each issue:
- use the exact supplied requirement ID and source chunk ID
- classify one supported issue type
- assign critical, high, medium, or low severity
- assign confidence from 0.0 to 1.0
- explain the gap using only the supplied requirement and source context
- ask one specific, answerable clarification question
- recommend the stakeholder role best placed to answer

Grounding rules:
- Do not invent a gap merely because an implementation could have more detail.
- Do not assume unstated technologies, policies, integrations, actors, or rules.
- Do not report an issue already resolved by another supplied requirement,
  the specification understanding, or the cited source chunk.
- Missing edge cases and error handling must be materially relevant to the
  requirement's stated behavior, not generic software advice.
- A recommended stakeholder is a routing recommendation, not a claim that the
  person or role exists in the source.
- Use unique issue IDs such as AMB-001.
- Do not rewrite requirements or propose implementation solutions.
"""


class AmbiguityModelProvider(Protocol):
    """Provider boundary for structured ambiguity detection."""

    def analyze(self, context: str) -> AmbiguityAnalysis:
        """Analyze every requirement for grounded ambiguity."""


class OpenAIAmbiguityProvider:
    """OpenAI Responses API implementation using structured output."""

    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def analyze(self, context: str) -> AmbiguityAnalysis:
        response = self._client.responses.parse(
            model=self._model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Analyze every requirement in this grounded specification "
                        f"context.\n\n{context}"
                    ),
                },
            ],
            text_format=AmbiguityAnalysis,
        )
        if response.output_parsed is None:
            raise RuntimeError("The model returned no ambiguity analysis.")
        return response.output_parsed
