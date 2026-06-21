from typing import Protocol

from openai import OpenAI

from app.models.engineering import EngineeringTranslation

SYSTEM_PROMPT = """You are the SpecBridge Business-to-Engineering Translator.

Translate the validated business specification into engineering-ready artifacts:
- user stories
- acceptance criteria
- REST APIs
- a structured OpenAPI 3.1 draft
- database entities
- validation rules
- backend tasks
- integration tasks
- permissions
- error codes
- event suggestions

Traceability rules:
- Every artifact must reference one or more supplied requirement IDs.
- Every artifact's source_chunks must exactly represent those requirements.
- The OpenAPI draft, each operation, and each schema are separate artifacts.
- Preserve requirement language and scope.

Inference rules:
- Never invent missing business behavior, fields, actors, permissions,
  integrations, statuses, error cases, or data retention rules.
- Set inferred=false only when the artifact is directly specified.
- Set inferred=true, provide inference_reason, and cite assumption_ids only when
  a small engineering interpretation is supported by the assumption ledger.
- Never create a new unstored assumption during translation.
- Do not use unconfirmed high-impact assumptions as settled design facts.
- When information is insufficient to safely generate an artifact, omit the
  artifact and add a blocked_output with the missing information and one
  clarification question.
- Existing ambiguities and conflicts are blockers when they affect the artifact.

OpenAPI rules:
- Produce a draft, not a claim of final API design.
- Include only operations and schemas supported by requirements.
- Do not invent request fields or response fields.

Quality rules:
- Keep user stories atomic.
- Acceptance criteria must be testable and use Given/When/Then.
- Tasks should describe implementation work without choosing an unstated stack.
- Event suggestions must be clearly inferred unless an event is explicit.
- Error codes must not invent error conditions.
"""


class TranslatorModelProvider(Protocol):
    """Provider boundary for structured engineering translation."""

    def analyze(self, context: str) -> EngineeringTranslation:
        """Translate business requirements into engineering artifacts."""


class OpenAITranslatorProvider:
    """OpenAI Responses API implementation using structured output."""

    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def analyze(self, context: str) -> EngineeringTranslation:
        response = self._client.responses.parse(
            model=self._model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Generate the grounded engineering translation from these "
                        f"validated inputs.\n\n{context}"
                    ),
                },
            ],
            text_format=EngineeringTranslation,
        )
        if response.output_parsed is None:
            raise RuntimeError("The model returned no engineering translation.")
        return response.output_parsed
