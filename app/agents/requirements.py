from typing import Protocol

from openai import OpenAI

from app.models.requirements import RequirementIntelligence

SYSTEM_PROMPT = """You are the SpecBridge Requirement Intelligence Agent.

The Specification Understanding Agent has already analyzed the whole document.
Use that understanding and every ordered source chunk to extract atomic,
traceable requirements.

Extract only these categories:
- functional requirements
- non-functional requirements
- business rules
- dependencies
- validation rules
- security requirements
- permissions
- notifications
- audit requirements

For every requirement:
- preserve an explicit source requirement ID when one exists
- otherwise generate a unique category-prefixed ID
- write a short title and one clear requirement statement
- assign critical, high, medium, or low priority
- assign confidence from 0.0 to 1.0 based on source clarity
- cite exactly one supplied chunk ID in source_chunk
- assign exactly one supported category

Rules:
- Extract only content supported by the specification.
- Split compound requirements into atomic requirements when the source supports it.
- Do not duplicate semantically equivalent requirements.
- Do not invent dependencies, permissions, notifications, or audit behavior.
- If priority is not explicit, infer conservatively and normally use medium.
- Generated IDs should use FR, NFR, BR, DEP, VAL, SEC, PERM, NOTIF, or AUD.
- Do not generate user stories.
- Do not design APIs, database schemas, or implementation plans.
"""


class RequirementModelProvider(Protocol):
    """Provider boundary for structured requirement extraction."""

    def analyze(self, context: str) -> RequirementIntelligence:
        """Extract categorized requirements from complete context."""


class OpenAIRequirementProvider:
    """OpenAI Responses API implementation using structured output."""

    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def analyze(self, context: str) -> RequirementIntelligence:
        response = self._client.responses.parse(
            model=self._model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Extract requirement intelligence from this complete "
                        f"specification context.\n\n{context}"
                    ),
                },
            ],
            text_format=RequirementIntelligence,
        )
        if response.output_parsed is None:
            raise RuntimeError("The model returned no requirement intelligence.")
        return response.output_parsed
