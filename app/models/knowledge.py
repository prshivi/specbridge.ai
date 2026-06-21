from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class EntityType(StrEnum):
    DOCUMENT = "document"
    SECTION = "section"
    REQUIREMENT = "requirement"
    BUSINESS_RULE = "business_rule"
    ACTOR = "actor"
    WORKFLOW = "workflow"
    INTEGRATION = "integration"
    CONSTRAINT = "constraint"
    VALIDATION = "validation"
    PERMISSION = "permission"
    NOTIFICATION = "notification"
    API_REFERENCE = "api_reference"
    DATA_ENTITY = "data_entity"
    GLOSSARY_TERM = "glossary_term"
    CONFLICT_ISSUE = "conflict_issue"
    MISSING_REQUIREMENT_ISSUE = "missing_requirement_issue"
    AMBIGUITY_ISSUE = "ambiguity_issue"
    ASSUMPTION = "assumption"
    ENGINEERING_ARTIFACT = "engineering_artifact"
    ARCHITECTURE_NODE = "architecture_node"


class RelationshipType(StrEnum):
    BELONGS_TO = "belongs_to"
    DEPENDS_ON = "depends_on"
    REFERENCES = "references"
    CONTAINS = "contains"
    USES = "uses"
    INTEGRATES_WITH = "integrates_with"
    VALIDATED_BY = "validated_by"
    REQUIRES = "requires"
    PERFORMED_BY = "performed_by"
    INVOLVES = "involves"
    RELATED_TO = "related_to"
    ARCHITECTURE_EDGE = "architecture_edge"


class KnowledgeEntity(BaseModel):
    """Shared provenance and confidence fields for graph entities."""

    id: str
    document_id: UUID
    entity_type: EntityType
    title: str
    description: str
    source_chunk_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Document(KnowledgeEntity):
    entity_type: Literal[EntityType.DOCUMENT] = EntityType.DOCUMENT


class Section(KnowledgeEntity):
    entity_type: Literal[EntityType.SECTION] = EntityType.SECTION


class Requirement(KnowledgeEntity):
    entity_type: Literal[EntityType.REQUIREMENT] = EntityType.REQUIREMENT


class BusinessRule(KnowledgeEntity):
    entity_type: Literal[EntityType.BUSINESS_RULE] = EntityType.BUSINESS_RULE


class Actor(KnowledgeEntity):
    entity_type: Literal[EntityType.ACTOR] = EntityType.ACTOR


class Workflow(KnowledgeEntity):
    entity_type: Literal[EntityType.WORKFLOW] = EntityType.WORKFLOW


class Integration(KnowledgeEntity):
    entity_type: Literal[EntityType.INTEGRATION] = EntityType.INTEGRATION


class Constraint(KnowledgeEntity):
    entity_type: Literal[EntityType.CONSTRAINT] = EntityType.CONSTRAINT


class Validation(KnowledgeEntity):
    entity_type: Literal[EntityType.VALIDATION] = EntityType.VALIDATION


class Permission(KnowledgeEntity):
    entity_type: Literal[EntityType.PERMISSION] = EntityType.PERMISSION


class Notification(KnowledgeEntity):
    entity_type: Literal[EntityType.NOTIFICATION] = EntityType.NOTIFICATION


class APIReference(KnowledgeEntity):
    entity_type: Literal[EntityType.API_REFERENCE] = EntityType.API_REFERENCE


class DataEntity(KnowledgeEntity):
    entity_type: Literal[EntityType.DATA_ENTITY] = EntityType.DATA_ENTITY


class GlossaryTerm(KnowledgeEntity):
    entity_type: Literal[EntityType.GLOSSARY_TERM] = EntityType.GLOSSARY_TERM


class KnowledgeRelationship(BaseModel):
    id: str
    document_id: UUID
    source_id: str
    target_id: str
    relationship_type: RelationshipType
    source_chunk_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeModel(BaseModel):
    document_id: UUID
    entities: list[KnowledgeEntity]
    relationships: list[KnowledgeRelationship]
    built_at: datetime


class KnowledgeBuildResult(BaseModel):
    document_id: UUID
    entity_count: int = Field(ge=0)
    relationship_count: int = Field(ge=0)
    entities_by_type: dict[EntityType, int]
    relationships_by_type: dict[RelationshipType, int]
    built_at: datetime


class KnowledgeGraphNode(BaseModel):
    id: str
    entity_type: EntityType
    title: str
    description: str
    source_chunk_ids: list[str]
    confidence: float
    metadata: dict[str, Any]


class KnowledgeGraphEdge(BaseModel):
    id: str
    source: str
    target: str
    relationship_type: RelationshipType
    source_chunk_ids: list[str]
    confidence: float
    metadata: dict[str, Any]


class KnowledgeGraph(BaseModel):
    document_id: UUID
    directed: bool = True
    multigraph: bool = True
    nodes: list[KnowledgeGraphNode]
    edges: list[KnowledgeGraphEdge]
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
