from typing import Protocol

from openai import OpenAI

from app.models.conflicts import ConflictAnalysis

SYSTEM_PROMPT = """You are the SpecBridge Conflict Detection Agent.

Compare the complete supplied requirement set and find direct contradictions.
A conflict exists only when two or more requirements cannot all be true or
implemented under the same stated conditions.

For every conflict:
- use a unique conflict ID such as CON-001
- describe the contradiction clearly
- provide evidence for at least two distinct supplied requirement IDs
- quote or closely paraphrase the contradictory statement for each item
- include every supporting source chunk
- assign critical, high, medium, or low severity
- assign confidence from 0.0 to 1.0
- recommend a resolution action without choosing an unsupported business policy

Grounding rules:
- Use only supplied requirements and source context.
- Do not invent requirements, policies, scopes, exceptions, or conditions.
- Do not label complementary requirements as conflicts.
- Do not label a broad rule and a clearly scoped exception as a conflict.
- Do not label missing detail, ambiguity, duplication, dependency, or different
  priorities as a conflict unless the requirement statements directly contradict.
- Requirements with different actors, states, regions, products, or time periods
  are not conflicts unless their stated scopes overlap.
- Return an empty conflicts list when no supported contradiction exists.
- Do not rewrite the specification or design an implementation.
"""


class ConflictModelProvider(Protocol):
    """Provider boundary for structured conflict detection."""

    def analyze(self, context: str) -> ConflictAnalysis:
        """Find grounded contradictions across the requirement set."""


class OpenAIConflictProvider:
    """OpenAI Responses API implementation using structured output."""

    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def analyze(self, context: str) -> ConflictAnalysis:
        response = self._client.responses.parse(
            model=self._model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Find direct contradictions in this complete grounded "
                        f"requirement set.\n\n{context}"
                    ),
                },
            ],
            text_format=ConflictAnalysis,
        )
        if response.output_parsed is None:
            raise RuntimeError("The model returned no conflict analysis.")
        return response.output_parsed
