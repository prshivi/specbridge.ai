from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class UnderstandingItem(BaseModel):
    """A named concept explicitly supported by the specification."""

    name: str
    description: str


class Stakeholder(UnderstandingItem):
    """A person, team, organization, or role with a project interest."""

    responsibilities: list[str] = Field(default_factory=list)


class Actor(UnderstandingItem):
    """A human or system actor interacting with the solution."""

    actor_type: str


class Workflow(BaseModel):
    """A workflow described by the specification."""

    name: str
    description: str
    actors: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)


class Integration(BaseModel):
    """An explicitly described external system integration."""

    name: str
    purpose: str
    external_system: str | None = None


class SpecificationUnderstanding(BaseModel):
    """Whole-document understanding used by downstream agents."""

    document_type: str
    project_summary: str
    business_objectives: list[str]
    stakeholders: list[Stakeholder]
    actors: list[Actor]
    modules: list[UnderstandingItem]
    workflows: list[Workflow]
    integrations: list[Integration]
    business_rules: list[str]
    constraints: list[str]
    explicit_assumptions: list[str]


class SpecificationUnderstandingResult(BaseModel):
    """Cached agent result and execution metadata."""

    document_id: UUID
    understanding: SpecificationUnderstanding
    cached: bool
    model: str
    prompt_version: str
    analyzed_at: datetime
