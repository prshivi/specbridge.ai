from typing import Protocol

from openai import OpenAI

from app.models.understanding import SpecificationUnderstanding

SYSTEM_PROMPT = """You are the SpecBridge Specification Understanding Agent.

Analyze the entire supplied specification before any downstream agent runs.
Return only the requested structured understanding.

Extract:
- the specification's document type or category
- a concise whole-project summary
- business objectives
- stakeholders
- human and system actors
- functional modules or capability areas
- workflows and their explicitly described steps
- integrations with external systems
- business rules
- technical, business, regulatory, operational, and delivery constraints
- assumptions only when they are explicitly stated in the source

Rules:
- Use only information supported by the supplied specification.
- Do not invent missing details.
- Use empty lists when a category is not present.
- Preserve important domain terminology.
- Distinguish stakeholders from actors.
- Do not generate user stories.
- Do not generate API designs, endpoints, schemas, or implementation plans.
- Do not recommend solutions or perform downstream analysis.
"""


class UnderstandingModelProvider(Protocol):
    """Provider boundary for structured specification analysis."""

    def analyze(self, context: str) -> SpecificationUnderstanding:
        """Analyze the complete specification context."""


class OpenAIUnderstandingProvider:
    """OpenAI Responses API implementation using Pydantic structured output."""

    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def analyze(self, context: str) -> SpecificationUnderstanding:
        response = self._client.responses.parse(
            model=self._model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Analyze this complete specification. Chunk boundaries and "
                        "source metadata are included for traceability.\n\n"
                        f"{context}"
                    ),
                },
            ],
            text_format=SpecificationUnderstanding,
        )
        if response.output_parsed is None:
            raise RuntimeError("The model returned no structured understanding.")
        return response.output_parsed
