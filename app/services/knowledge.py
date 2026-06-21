import hashlib
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from uuid import UUID

import networkx as nx

from app.core.config import Settings
from app.core.exceptions import DocumentChunksNotFoundError, KnowledgeGraphNotFoundError
from app.models.document import ChunkType, DocumentChunk
from app.models.knowledge import (
    EntityType,
    KnowledgeBuildResult,
    KnowledgeEntity,
    KnowledgeGraph,
    KnowledgeGraphEdge,
    KnowledgeGraphNode,
    KnowledgeModel,
    KnowledgeRelationship,
    RelationshipType,
)
from app.services.chunks import ChunkService
from app.services.knowledge_store import KnowledgeGraphStore

EXPLICIT_REQUIREMENT = re.compile(r"\b((?:REQ|FR|NFR)[-_ ]?\d+)\b", re.IGNORECASE)
EXPLICIT_RULE = re.compile(r"\b(BR[-_ ]?\d+)\b", re.IGNORECASE)
DEPENDENCY = re.compile(
    r"\b(?:depends on|dependent on|requires)\s+((?:REQ|FR|NFR)[-_ ]?\d+)\b",
    re.IGNORECASE,
)
RULE_REFERENCE = re.compile(
    r"\b(?:references?|according to|subject to)\s+(BR[-_ ]?\d+)\b",
    re.IGNORECASE,
)
ACTOR_LABEL = re.compile(
    r"(?im)^\s*(?:actor|role|stakeholder)\s*[:\-]\s*([A-Za-z][\w /&-]{1,60})"
)
ACTOR_PHRASE = re.compile(
    r"\b(?:as an?|only)\s+([A-Za-z][A-Za-z -]{1,35}?)(?=,|\s+(?:can|may|must|shall)\b)",
    re.IGNORECASE,
)
INTEGRATION_LABEL = re.compile(
    r"(?i)\b(?:integration|external system)\s*[:\-]\s*"
    r"([A-Za-z][\w .&/-]{1,80}?)(?=\.|,|;|\n|$)"
)
INTEGRATION_PHRASE = re.compile(
    r"\b(?:integrates? with|connects? to|sends? (?:data )?to|"
    r"receives? (?:data )?from)\s+([A-Z][A-Za-z0-9 .&_-]{1,60})"
)
DATA_ENTITY_LABEL = re.compile(
    r"(?i)\b(?:data entity|entity|record|table)\s*[:\-]\s*"
    r"([A-Za-z][\w -]{1,60}?)(?=\.|,|;|\n|$)"
)
GLOSSARY_ENTRY = re.compile(
    r"(?m)^\s*([A-Za-z][A-Za-z0-9 /_-]{1,50})\s*[:\-]\s+(.{8,240})$"
)
API_REFERENCE_PATTERN = re.compile(
    r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[A-Za-z0-9_./{}:-]+)",
    re.IGNORECASE,
)
PERMISSION_PATTERN = re.compile(
    r"\b(?:only\s+.+?\s+(?:may|can|shall)|permission|authori[sz]ed|"
    r"access control|role)\b",
    re.IGNORECASE,
)
VALIDATION_PATTERN = re.compile(
    r"\b(?:validate|validation|valid|invalid|required field|acceptance criteria|"
    r"given\b.+\bwhen\b.+\bthen)\b",
    re.IGNORECASE | re.DOTALL,
)
NOTIFICATION_PATTERN = re.compile(
    r"\b(?:notify|notification|send(?:s|ing)?\s+(?:an?\s+)?"
    r"(?:email|sms|message)|alert)\b",
    re.IGNORECASE,
)
CONSTRAINT_PATTERN = re.compile(
    r"\b(?:constraint|must not|shall not|no more than|at least|at most|"
    r"within\s+\d+|limited to|maximum|minimum)\b",
    re.IGNORECASE,
)
GLOSSARY_HEADING = re.compile(
    r"\b(?:glossary|terminology|definitions?)\b", re.IGNORECASE
)


class KnowledgeGraphService:
    """Extract, persist, and reconstruct a deterministic specification graph."""

    def __init__(
        self,
        settings: Settings,
        *,
        chunk_service: ChunkService | None = None,
        store: KnowledgeGraphStore | None = None,
    ) -> None:
        self._chunk_service = chunk_service or ChunkService(settings)
        self._store = store or KnowledgeGraphStore(settings.understanding_cache_db)

    def build(self, document_id: UUID) -> KnowledgeBuildResult:
        chunks = self._chunk_service.get_chunks(document_id)
        if not chunks:
            raise DocumentChunksNotFoundError(
                "No parsed chunks were found for this document."
            )
        model = self._extract(document_id, chunks)
        self._store.replace(model)
        return self._build_result(model)

    def get(self, document_id: UUID) -> KnowledgeModel:
        model = self._store.get(document_id)
        if model is None:
            raise KnowledgeGraphNotFoundError(
                "Knowledge graph has not been built for this document."
            )
        return model

    def get_graph(self, document_id: UUID) -> KnowledgeGraph:
        model = self.get(document_id)
        graph = self._to_networkx(model)
        return KnowledgeGraph(
            document_id=document_id,
            nodes=[
                KnowledgeGraphNode(
                    id=node_id,
                    entity_type=data["entity_type"],
                    title=data["title"],
                    description=data["description"],
                    source_chunk_ids=data["source_chunk_ids"],
                    confidence=data["confidence"],
                    metadata=data["metadata"],
                )
                for node_id, data in graph.nodes(data=True)
            ],
            edges=[
                KnowledgeGraphEdge(
                    id=data["id"],
                    source=source,
                    target=target,
                    relationship_type=data["relationship_type"],
                    source_chunk_ids=data["source_chunk_ids"],
                    confidence=data["confidence"],
                    metadata=data["metadata"],
                )
                for source, target, _, data in graph.edges(keys=True, data=True)
            ],
            node_count=graph.number_of_nodes(),
            edge_count=graph.number_of_edges(),
        )

    def _extract(
        self,
        document_id: UUID,
        chunks: list[DocumentChunk],
    ) -> KnowledgeModel:
        entities: dict[str, KnowledgeEntity] = {}
        relationships: dict[str, KnowledgeRelationship] = {}
        section_by_chunk: dict[str, str] = {}
        requirement_by_ref: dict[str, str] = {}
        rule_by_ref: dict[str, str] = {}

        document = self._entity(
            document_id,
            EntityType.DOCUMENT,
            self._document_title(chunks),
            self._document_description(chunks),
            [chunk.id for chunk in chunks],
            1.0,
            {"chunk_count": len(chunks)},
        )
        entities[document.id] = document

        for chunk in chunks:
            section_title = chunk.heading or chunk.section
            if section_title:
                section = self._merge_entity(
                    entities,
                    self._entity(
                        document_id,
                        EntityType.SECTION,
                        section_title,
                        f"Section {chunk.section or section_title}",
                        [chunk.id],
                        1.0,
                        {"section_number": chunk.section, "page": chunk.page},
                        identity_key=f"{chunk.section or ''}|{section_title}",
                    ),
                )
                section_by_chunk[chunk.id] = section.id

        for chunk in chunks:
            if chunk.chunk_type is ChunkType.REQUIREMENT:
                requirement = self._merge_entity(
                    entities,
                    self._entity_from_chunk(
                        document_id, EntityType.REQUIREMENT, chunk, "Requirement"
                    ),
                )
                explicit = EXPLICIT_REQUIREMENT.search(chunk.text)
                if explicit:
                    normalized = self._normalize_reference(explicit.group(1))
                    requirement.metadata["explicit_id"] = normalized
                    requirement_by_ref[normalized] = requirement.id
                if chunk.id in section_by_chunk:
                    self._add_relationship(
                        relationships,
                        document_id,
                        requirement.id,
                        section_by_chunk[chunk.id],
                        RelationshipType.BELONGS_TO,
                        [chunk.id],
                        1.0,
                    )

            if chunk.chunk_type is ChunkType.BUSINESS_RULE:
                rule = self._merge_entity(
                    entities,
                    self._entity_from_chunk(
                        document_id, EntityType.BUSINESS_RULE, chunk, "Business Rule"
                    ),
                )
                explicit = EXPLICIT_RULE.search(chunk.text)
                if explicit:
                    normalized = self._normalize_reference(explicit.group(1))
                    rule.metadata["explicit_id"] = normalized
                    rule_by_ref[normalized] = rule.id

            if chunk.chunk_type is ChunkType.WORKFLOW:
                self._merge_entity(
                    entities,
                    self._entity_from_chunk(
                        document_id, EntityType.WORKFLOW, chunk, "Workflow"
                    ),
                )

            self._extract_supporting_entities(document_id, chunk, entities)

        requirements = [
            entity
            for entity in entities.values()
            if entity.entity_type is EntityType.REQUIREMENT
        ]
        self._link_explicit_references(
            document_id,
            chunks,
            requirements,
            requirement_by_ref,
            rule_by_ref,
            relationships,
        )
        self._link_structural_entities(
            document_id,
            chunks,
            requirements,
            entities,
            relationships,
        )
        return KnowledgeModel(
            document_id=document_id,
            entities=sorted(
                entities.values(), key=lambda item: (item.entity_type.value, item.id)
            ),
            relationships=sorted(
                relationships.values(),
                key=lambda item: (item.relationship_type.value, item.id),
            ),
            built_at=datetime.now(UTC),
        )

    def _extract_supporting_entities(
        self,
        document_id: UUID,
        chunk: DocumentChunk,
        entities: dict[str, KnowledgeEntity],
    ) -> None:
        text = chunk.text.strip()
        candidates: list[
            tuple[EntityType, str, str, float, dict[str, object]]
        ] = []
        for pattern in (ACTOR_LABEL, ACTOR_PHRASE):
            candidates.extend(
                (EntityType.ACTOR, match.group(1), match.group(0), 0.85, {})
                for match in pattern.finditer(text)
            )
        for pattern in (INTEGRATION_LABEL, INTEGRATION_PHRASE):
            candidates.extend(
                (EntityType.INTEGRATION, match.group(1), match.group(0), 0.9, {})
                for match in pattern.finditer(text)
            )
        candidates.extend(
            (EntityType.DATA_ENTITY, match.group(1), match.group(0), 0.9, {})
            for match in DATA_ENTITY_LABEL.finditer(text)
        )
        for match in API_REFERENCE_PATTERN.finditer(text):
            method, path = match.groups()
            candidates.append(
                (
                    EntityType.API_REFERENCE,
                    f"{method.upper()} {path}",
                    match.group(0),
                    1.0,
                    {"method": method.upper(), "path": path},
                )
            )
        if (
            chunk.chunk_type is ChunkType.ACCEPTANCE_CRITERIA
            or VALIDATION_PATTERN.search(text)
        ):
            candidates.append(
                (
                    EntityType.VALIDATION,
                    chunk.heading or self._short_title(text, "Validation"),
                    text,
                    0.9
                    if chunk.chunk_type is ChunkType.ACCEPTANCE_CRITERIA
                    else 0.75,
                    {},
                )
            )
        for pattern, entity_type, fallback in (
            (PERMISSION_PATTERN, EntityType.PERMISSION, "Permission"),
            (NOTIFICATION_PATTERN, EntityType.NOTIFICATION, "Notification"),
            (CONSTRAINT_PATTERN, EntityType.CONSTRAINT, "Constraint"),
        ):
            if pattern.search(text):
                candidates.append(
                    (
                        entity_type,
                        self._short_title(text, fallback),
                        text,
                        0.8,
                        {},
                    )
                )
        if GLOSSARY_HEADING.search(chunk.heading or ""):
            candidates.extend(
                (
                    EntityType.GLOSSARY_TERM,
                    match.group(1),
                    match.group(2),
                    0.95,
                    {},
                )
                for match in GLOSSARY_ENTRY.finditer(text)
            )

        for entity_type, title, description, confidence, metadata in candidates:
            title = title.strip(" .:-")
            if len(title) < 2:
                continue
            self._merge_entity(
                entities,
                self._entity(
                    document_id,
                    entity_type,
                    title,
                    description.strip(),
                    [chunk.id],
                    confidence,
                    {"page": chunk.page, "section": chunk.section, **metadata},
                ),
            )

    def _link_explicit_references(
        self,
        document_id: UUID,
        chunks: list[DocumentChunk],
        requirements: list[KnowledgeEntity],
        requirement_ids: dict[str, str],
        rule_ids: dict[str, str],
        relationships: dict[str, KnowledgeRelationship],
    ) -> None:
        chunk_map = {chunk.id: chunk for chunk in chunks}
        for requirement in requirements:
            chunk = chunk_map[requirement.source_chunk_ids[0]]
            for match in DEPENDENCY.finditer(chunk.text):
                target = requirement_ids.get(self._normalize_reference(match.group(1)))
                if target and target != requirement.id:
                    self._add_relationship(
                        relationships,
                        document_id,
                        requirement.id,
                        target,
                        RelationshipType.DEPENDS_ON,
                        [chunk.id],
                        1.0,
                    )
            for match in RULE_REFERENCE.finditer(chunk.text):
                target = rule_ids.get(self._normalize_reference(match.group(1)))
                if target:
                    self._add_relationship(
                        relationships,
                        document_id,
                        requirement.id,
                        target,
                        RelationshipType.REFERENCES,
                        [chunk.id],
                        1.0,
                    )

    def _link_structural_entities(
        self,
        document_id: UUID,
        chunks: list[DocumentChunk],
        requirements: list[KnowledgeEntity],
        entities: dict[str, KnowledgeEntity],
        relationships: dict[str, KnowledgeRelationship],
    ) -> None:
        chunk_map = {chunk.id: chunk for chunk in chunks}
        by_type: dict[EntityType, list[KnowledgeEntity]] = defaultdict(list)
        for entity in entities.values():
            by_type[entity.entity_type].append(entity)

        for requirement in requirements:
            source_chunk = chunk_map[requirement.source_chunk_ids[0]]
            for workflow in by_type[EntityType.WORKFLOW]:
                workflow_chunk = chunk_map[workflow.source_chunk_ids[0]]
                explicit_id = requirement.metadata.get("explicit_id")
                referenced = bool(
                    explicit_id
                    and explicit_id
                    in {
                        self._normalize_reference(value)
                        for value in EXPLICIT_REQUIREMENT.findall(workflow_chunk.text)
                    }
                )
                same_section = bool(
                    source_chunk.section
                    and source_chunk.section == workflow_chunk.section
                )
                if referenced or same_section:
                    self._add_relationship(
                        relationships,
                        document_id,
                        workflow.id,
                        requirement.id,
                        RelationshipType.CONTAINS,
                        list(dict.fromkeys([workflow_chunk.id, source_chunk.id])),
                        1.0 if referenced else 0.7,
                        {
                            "basis": (
                                "explicit_reference" if referenced else "same_section"
                            )
                        },
                    )

            for entity_type, relationship_type in (
                (EntityType.DATA_ENTITY, RelationshipType.USES),
                (EntityType.INTEGRATION, RelationshipType.INTEGRATES_WITH),
                (EntityType.VALIDATION, RelationshipType.VALIDATED_BY),
                (EntityType.PERMISSION, RelationshipType.REQUIRES),
            ):
                for target in by_type[entity_type]:
                    target_chunk = chunk_map[target.source_chunk_ids[0]]
                    title_mentioned = bool(
                        len(target.title) >= 3
                        and target.title.lower() in source_chunk.text.lower()
                    )
                    same_chunk = target_chunk.id == source_chunk.id
                    same_section = bool(
                        source_chunk.section
                        and source_chunk.section == target_chunk.section
                    )
                    if title_mentioned or same_chunk or same_section:
                        direct = title_mentioned or same_chunk
                        self._add_relationship(
                            relationships,
                            document_id,
                            requirement.id,
                            target.id,
                            relationship_type,
                            list(dict.fromkeys([source_chunk.id, target_chunk.id])),
                            0.95 if direct else 0.7,
                            {"basis": "text_or_chunk" if direct else "same_section"},
                        )

    @staticmethod
    def _to_networkx(model: KnowledgeModel) -> nx.MultiDiGraph:
        graph = nx.MultiDiGraph(document_id=str(model.document_id))
        for entity in model.entities:
            graph.add_node(
                entity.id,
                entity_type=entity.entity_type,
                title=entity.title,
                description=entity.description,
                source_chunk_ids=entity.source_chunk_ids,
                confidence=entity.confidence,
                metadata=entity.metadata,
            )
        for relationship in model.relationships:
            graph.add_edge(
                relationship.source_id,
                relationship.target_id,
                key=relationship.id,
                id=relationship.id,
                relationship_type=relationship.relationship_type,
                source_chunk_ids=relationship.source_chunk_ids,
                confidence=relationship.confidence,
                metadata=relationship.metadata,
            )
        return graph

    @staticmethod
    def _merge_entity(
        entities: dict[str, KnowledgeEntity],
        candidate: KnowledgeEntity,
    ) -> KnowledgeEntity:
        existing = entities.get(candidate.id)
        if existing is None:
            entities[candidate.id] = candidate
            return candidate
        existing.source_chunk_ids = list(
            dict.fromkeys([*existing.source_chunk_ids, *candidate.source_chunk_ids])
        )
        existing.confidence = max(existing.confidence, candidate.confidence)
        existing.metadata.update(
            {key: value for key, value in candidate.metadata.items() if value is not None}
        )
        if len(candidate.description) > len(existing.description):
            existing.description = candidate.description
        return existing

    @classmethod
    def _entity_from_chunk(
        cls,
        document_id: UUID,
        entity_type: EntityType,
        chunk: DocumentChunk,
        fallback: str,
    ) -> KnowledgeEntity:
        explicit_pattern = (
            EXPLICIT_REQUIREMENT
            if entity_type is EntityType.REQUIREMENT
            else EXPLICIT_RULE
            if entity_type is EntityType.BUSINESS_RULE
            else None
        )
        explicit = explicit_pattern.search(chunk.text) if explicit_pattern else None
        title = (
            cls._normalize_reference(explicit.group(1))
            if explicit
            else cls._short_title(chunk.text, fallback)
        )
        return cls._entity(
            document_id,
            entity_type,
            title,
            chunk.text.strip(),
            [chunk.id],
            1.0 if explicit or chunk.chunk_type.value == entity_type.value else 0.9,
            {
                "page": chunk.page,
                "section": chunk.section,
                "heading": chunk.heading,
                "chunk_type": chunk.chunk_type.value,
            },
        )

    @staticmethod
    def _entity(
        document_id: UUID,
        entity_type: EntityType,
        title: str,
        description: str,
        source_chunk_ids: list[str],
        confidence: float,
        metadata: dict[str, object],
        identity_key: str | None = None,
    ) -> KnowledgeEntity:
        identity = identity_key or title
        normalized = re.sub(r"\W+", "-", identity.lower()).strip("-")
        digest = hashlib.sha1(identity.lower().encode()).hexdigest()[:10]
        suffix = normalized[:48] or digest
        return KnowledgeEntity(
            id=f"kg:{document_id}:{entity_type.value}:{suffix}:{digest}",
            document_id=document_id,
            entity_type=entity_type,
            title=title.strip(),
            description=description.strip(),
            source_chunk_ids=source_chunk_ids,
            confidence=confidence,
            metadata=metadata,
        )

    @staticmethod
    def _add_relationship(
        relationships: dict[str, KnowledgeRelationship],
        document_id: UUID,
        source_id: str,
        target_id: str,
        relationship_type: RelationshipType,
        source_chunk_ids: list[str],
        confidence: float,
        metadata: dict[str, object] | None = None,
    ) -> None:
        raw = f"{source_id}|{relationship_type.value}|{target_id}"
        relationship_id = f"kgr:{hashlib.sha1(raw.encode()).hexdigest()[:16]}"
        relationships[relationship_id] = KnowledgeRelationship(
            id=relationship_id,
            document_id=document_id,
            source_id=source_id,
            target_id=target_id,
            relationship_type=relationship_type,
            source_chunk_ids=source_chunk_ids,
            confidence=confidence,
            metadata=metadata or {},
        )

    @staticmethod
    def _build_result(model: KnowledgeModel) -> KnowledgeBuildResult:
        entity_counts = Counter(entity.entity_type for entity in model.entities)
        relationship_counts = Counter(
            relationship.relationship_type for relationship in model.relationships
        )
        return KnowledgeBuildResult(
            document_id=model.document_id,
            entity_count=len(model.entities),
            relationship_count=len(model.relationships),
            entities_by_type={
                entity_type: entity_counts[entity_type] for entity_type in EntityType
            },
            relationships_by_type={
                relationship_type: relationship_counts[relationship_type]
                for relationship_type in RelationshipType
            },
            built_at=model.built_at,
        )

    @staticmethod
    def _normalize_reference(value: str) -> str:
        return re.sub(r"[-_ ]+", "-", value.upper())

    @staticmethod
    def _short_title(text: str, fallback: str) -> str:
        first_line = next(
            (line.strip() for line in text.splitlines() if line.strip()), fallback
        )
        return re.sub(r"^[*-]\s*", "", first_line)[:80].rstrip(" .:") or fallback

    @staticmethod
    def _document_title(chunks: list[DocumentChunk]) -> str:
        return next(
            (chunk.heading for chunk in chunks if chunk.heading),
            "Uploaded Specification",
        )

    @staticmethod
    def _document_description(chunks: list[DocumentChunk]) -> str:
        return " ".join(
            chunk.text.strip() for chunk in chunks if chunk.text.strip()
        )[:500]
