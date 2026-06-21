from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class DeveloperQuestion(BaseModel):
    """A developer question about one uploaded specification."""

    question: str = Field(min_length=1, max_length=4000)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Question cannot be blank.")
        return normalized


class CopilotCitation(BaseModel):
    """Citation to an allowed grounded source."""

    source_chunk: str
    requirement_ids: list[str] = Field(default_factory=list)
    architecture_ids: list[str] = Field(default_factory=list)


class CopilotAnswer(BaseModel):
    """Structured grounded answer or exact unavailable fallback."""

    answer: str
    available: bool
    clarification_question: str | None = None
    citations: list[CopilotCitation]

    @model_validator(mode="after")
    def validate_availability(self) -> "CopilotAnswer":
        if self.available:
            if not self.citations:
                raise ValueError("Available answers require source chunk citations.")
            if self.clarification_question is not None:
                raise ValueError(
                    "Available answers must not include a clarification question."
                )
        else:
            if self.answer != "Not enough information.":
                raise ValueError(
                    'Unavailable answers must be exactly "Not enough information."'
                )
            if not self.clarification_question:
                raise ValueError(
                    "Unavailable answers require a clarification question."
                )
            if self.citations:
                raise ValueError("Unavailable answers must not include citations.")
        return self


class DeveloperCopilotResponse(BaseModel):
    """Persisted developer copilot exchange."""

    interaction_id: str
    document_id: UUID
    question: str
    answer: str
    available: bool
    clarification_question: str | None
    citations: list[CopilotCitation]
    model: str
    prompt_version: str
    answered_at: datetime
