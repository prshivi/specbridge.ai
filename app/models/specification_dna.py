from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class EvidenceBase(BaseModel):
    """Grounding required for every extracted DNA item."""

    confidence: float = Field(ge=0.0, le=1.0)
    source_chunk_ids: list[str] = Field(min_length=1)
    source_document_sections: list[str] = Field(min_length=1)

    @field_validator("source_chunk_ids", "source_document_sections")
    @classmethod
    def unique_nonempty_values(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if not cleaned:
            raise ValueError("Evidence references cannot be empty.")
        return list(dict.fromkeys(cleaned))


class EvidenceText(EvidenceBase):
    value: str = Field(min_length=1)


class NamedDNAItem(EvidenceBase):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class ActorDNA(NamedDNAItem):
    actor_type: str | None = None


class UserPersonaDNA(NamedDNAItem):
    goals: list[str] = Field(default_factory=list)
    needs: list[str] = Field(default_factory=list)


class WorkflowDNA(NamedDNAItem):
    actors: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)


class IntegrationDNA(NamedDNAItem):
    external_system: str | None = None
    purpose: str | None = None


class GlossaryDNA(EvidenceBase):
    term: str = Field(min_length=1)
    definition: str = Field(min_length=1)


class SpecificationDNA(BaseModel):
    """Evidence-grounded whole-document understanding."""

    project_name: EvidenceText | None = None
    project_summary: EvidenceText | None = None
    business_objectives: list[EvidenceText] = Field(default_factory=list)
    actors: list[ActorDNA] = Field(default_factory=list)
    user_personas: list[UserPersonaDNA] = Field(default_factory=list)
    modules: list[NamedDNAItem] = Field(default_factory=list)
    workflows: list[WorkflowDNA] = Field(default_factory=list)
    integrations: list[IntegrationDNA] = Field(default_factory=list)
    business_rules: list[EvidenceText] = Field(default_factory=list)
    constraints: list[EvidenceText] = Field(default_factory=list)
    explicit_assumptions: list[EvidenceText] = Field(default_factory=list)
    glossary: list[GlossaryDNA] = Field(default_factory=list)
    key_terminology: list[GlossaryDNA] = Field(default_factory=list)


class SpecificationDNAResult(BaseModel):
    document_id: UUID
    specification_dna: SpecificationDNA
    cached: bool
    model: str
    agent_version: str
    source_fingerprint: str
    execution_time_ms: float = Field(ge=0.0)
    generated_at: datetime
