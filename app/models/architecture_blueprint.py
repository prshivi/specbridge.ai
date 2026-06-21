from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class SolutionArchitectureStyle(StrEnum):
    MONOLITH = "monolith"
    MODULAR_MONOLITH = "modular_monolith"
    MICROSERVICES = "microservices"
    EVENT_DRIVEN = "event_driven"
    SERVERLESS = "serverless"
    HYBRID = "hybrid"
    UNDETERMINED = "undetermined"


class ArchitectureRecommendationType(StrEnum):
    HIGH_LEVEL_ARCHITECTURE = "high_level_architecture"
    MODULE = "module"
    SERVICE_RESPONSIBILITY = "service_responsibility"
    DATABASE = "database"
    EXTERNAL_INTEGRATION = "external_integration"
    COMMUNICATION_PATTERN = "communication_pattern"
    AUTHENTICATION_AUTHORIZATION = "authentication_authorization"
    CACHING = "caching"
    MESSAGING = "messaging"
    OBSERVABILITY = "observability"
    DEPLOYMENT = "deployment"
    SCALABILITY = "scalability"
    RELIABILITY = "reliability"
    SECURITY = "security"


class ArchitectureProvenance(StrEnum):
    DOCUMENT_BACKED = "document_backed"
    AI_RECOMMENDATION = "ai_recommendation"
    AI_ASSUMPTION = "ai_assumption"
    NEEDS_CLARIFICATION = "needs_clarification"


class ArchitectureDiagramType(StrEnum):
    SYSTEM_CONTEXT = "system_context"
    COMPONENT = "component"
    CONTAINER = "container"
    SEQUENCE = "sequence"
    MODULE_DEPENDENCY = "module_dependency"


class ArchitectureRecommendationItem(BaseModel):
    recommendation_id: str = Field(min_length=1)
    recommendation_type: ArchitectureRecommendationType
    title: str = Field(min_length=1)
    recommendation: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1)
    provenance: ArchitectureProvenance
    evidence_text: str | None = None
    related_requirement_ids: list[str] = Field(min_length=1)
    related_artifact_ids: list[str] = Field(min_length=1)
    related_assumption_ids: list[str] = Field(default_factory=list)
    source_chunk_ids: list[str] = Field(min_length=1)
    source_sections: list[str] = Field(min_length=1)
    traceability_score: float = Field(ge=0.0, le=1.0)
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "related_requirement_ids",
        "related_artifact_ids",
        "related_assumption_ids",
        "source_chunk_ids",
        "source_sections",
    )
    @classmethod
    def unique_values(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @model_validator(mode="after")
    def validate_provenance(self) -> "ArchitectureRecommendationItem":
        if self.provenance is ArchitectureProvenance.DOCUMENT_BACKED:
            if not self.evidence_text:
                raise ValueError(
                    "Document-backed architecture recommendations require evidence."
                )
            if self.related_assumption_ids:
                raise ValueError(
                    "Document-backed recommendations cannot cite assumptions."
                )
        elif self.provenance is ArchitectureProvenance.AI_ASSUMPTION:
            if not self.related_assumption_ids:
                raise ValueError(
                    "AI-assumption recommendations require assumption IDs."
                )
        elif self.provenance is ArchitectureProvenance.NEEDS_CLARIFICATION:
            if "needs clarification" not in self.recommendation.casefold():
                raise ValueError(
                    "Unresolved architecture recommendations must say "
                    "'Needs clarification'."
                )
        return self


class ArchitectureDiagram(BaseModel):
    diagram_id: str = Field(min_length=1)
    diagram_type: ArchitectureDiagramType
    title: str = Field(min_length=1)
    mermaid: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1)
    provenance: ArchitectureProvenance
    related_requirement_ids: list[str] = Field(min_length=1)
    related_artifact_ids: list[str] = Field(min_length=1)
    related_assumption_ids: list[str] = Field(default_factory=list)
    source_chunk_ids: list[str] = Field(min_length=1)
    source_sections: list[str] = Field(min_length=1)
    traceability_score: float = Field(ge=0.0, le=1.0)

    @field_validator(
        "related_requirement_ids",
        "related_artifact_ids",
        "related_assumption_ids",
        "source_chunk_ids",
        "source_sections",
    )
    @classmethod
    def unique_values(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @model_validator(mode="after")
    def validate_mermaid_and_provenance(self) -> "ArchitectureDiagram":
        sequence = self.diagram_type is ArchitectureDiagramType.SEQUENCE
        if sequence and not self.mermaid.lstrip().startswith("sequenceDiagram"):
            raise ValueError("Sequence diagrams must start with sequenceDiagram.")
        if not sequence and not self.mermaid.lstrip().startswith(
            ("flowchart", "graph")
        ):
            raise ValueError(
                "Architecture diagrams must start with flowchart or graph."
            )
        if (
            self.provenance is ArchitectureProvenance.AI_ASSUMPTION
            and not self.related_assumption_ids
        ):
            raise ValueError("AI-assumption diagrams require assumption IDs.")
        if (
            self.provenance is ArchitectureProvenance.DOCUMENT_BACKED
            and self.related_assumption_ids
        ):
            raise ValueError(
                "Document-backed diagrams cannot cite assumptions."
            )
        return self


class ArchitectureBlueprint(BaseModel):
    summary: str = Field(min_length=1)
    recommended_style: SolutionArchitectureStyle
    recommendations: list[ArchitectureRecommendationItem] = Field(min_length=1)
    diagrams: list[ArchitectureDiagram] = Field(min_length=5)

    @model_validator(mode="after")
    def validate_complete_architecture(self) -> "ArchitectureBlueprint":
        present = {item.recommendation_type for item in self.recommendations}
        required = set(ArchitectureRecommendationType)
        missing = required - present
        if missing:
            raise ValueError(
                "Architecture Blueprint is missing recommendation types: "
                + ", ".join(sorted(item.value for item in missing))
            )
        diagram_types = [item.diagram_type for item in self.diagrams]
        if len(diagram_types) != len(set(diagram_types)):
            raise ValueError("Architecture diagram types must be unique.")
        missing_diagrams = set(ArchitectureDiagramType) - set(diagram_types)
        if missing_diagrams:
            raise ValueError(
                "Architecture Blueprint is missing diagram types: "
                + ", ".join(sorted(item.value for item in missing_diagrams))
            )
        return self


class ArchitectureBlueprintResult(BaseModel):
    document_id: UUID
    architecture: ArchitectureBlueprint
    total_recommendations: int = Field(ge=0)
    total_diagrams: int = Field(ge=0)
    clarification_recommendations: int = Field(ge=0)
    cached: bool
    model: str
    agent_version: str
    source_fingerprint: str
    execution_time_ms: float = Field(ge=0.0)
    generated_at: datetime
    knowledge_graph_updated: bool


class ArchitectureDiagramCollection(BaseModel):
    document_id: UUID
    diagrams: list[ArchitectureDiagram]
