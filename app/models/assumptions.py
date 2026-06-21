from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class FactRecord(BaseModel):
    """An AI output claim directly supported by source text."""

    fact_id: str
    fact: str
    affected_outputs: list[str] = Field(min_length=1)
    source_chunk: str


class AssumptionRecord(BaseModel):
    """An inference not explicitly stated in the source specification."""

    assumption_id: str
    assumption: str
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    affected_outputs: list[str] = Field(min_length=1)
    needs_confirmation: bool
    source_chunk: str


class AssumptionLedger(BaseModel):
    """Strict separation between source facts and AI assumptions."""

    facts: list[FactRecord]
    assumptions: list[AssumptionRecord]


class AssumptionLedgerResult(BaseModel):
    """Stored assumption ledger plus execution metadata."""

    document_id: UUID
    facts: list[FactRecord]
    assumptions: list[AssumptionRecord]
    total_facts: int = Field(ge=0)
    total_assumptions: int = Field(ge=0)
    pending_confirmation: int = Field(ge=0)
    cached: bool
    model: str
    prompt_version: str
    analyzed_at: datetime
