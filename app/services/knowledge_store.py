import json
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import UUID

from app.models.knowledge import (
    KnowledgeEntity,
    KnowledgeModel,
    KnowledgeRelationship,
)


class KnowledgeGraphStore:
    """Normalized SQLite persistence for deterministic knowledge graphs."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def replace(self, model: KnowledgeModel) -> None:
        document_id = str(model.document_id)
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM knowledge_relationships WHERE document_id = ?",
                (document_id,),
            )
            connection.execute(
                "DELETE FROM knowledge_entities WHERE document_id = ?",
                (document_id,),
            )
            connection.execute(
                "DELETE FROM knowledge_builds WHERE document_id = ?",
                (document_id,),
            )
            connection.executemany(
                """
                INSERT INTO knowledge_entities (
                    id, document_id, entity_type, title, description,
                    source_chunk_ids_json, confidence, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        entity.id,
                        document_id,
                        entity.entity_type.value,
                        entity.title,
                        entity.description,
                        json.dumps(entity.source_chunk_ids),
                        entity.confidence,
                        json.dumps(entity.metadata, sort_keys=True),
                    )
                    for entity in model.entities
                ],
            )
            connection.executemany(
                """
                INSERT INTO knowledge_relationships (
                    id, document_id, source_id, target_id, relationship_type,
                    source_chunk_ids_json, confidence, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        relationship.id,
                        document_id,
                        relationship.source_id,
                        relationship.target_id,
                        relationship.relationship_type.value,
                        json.dumps(relationship.source_chunk_ids),
                        relationship.confidence,
                        json.dumps(relationship.metadata, sort_keys=True),
                    )
                    for relationship in model.relationships
                ],
            )
            connection.execute(
                """
                INSERT INTO knowledge_builds (document_id, built_at)
                VALUES (?, ?)
                """,
                (document_id, model.built_at.isoformat()),
            )

    def get(self, document_id: UUID) -> KnowledgeModel | None:
        with self._connect() as connection:
            build = connection.execute(
                "SELECT built_at FROM knowledge_builds WHERE document_id = ?",
                (str(document_id),),
            ).fetchone()
            if build is None:
                return None
            entity_rows = connection.execute(
                """
                SELECT * FROM knowledge_entities
                WHERE document_id = ?
                ORDER BY entity_type, id
                """,
                (str(document_id),),
            ).fetchall()
            relationship_rows = connection.execute(
                """
                SELECT * FROM knowledge_relationships
                WHERE document_id = ?
                ORDER BY relationship_type, id
                """,
                (str(document_id),),
            ).fetchall()
        return KnowledgeModel(
            document_id=document_id,
            entities=[
                KnowledgeEntity(
                    id=row["id"],
                    document_id=document_id,
                    entity_type=row["entity_type"],
                    title=row["title"],
                    description=row["description"],
                    source_chunk_ids=json.loads(row["source_chunk_ids_json"]),
                    confidence=row["confidence"],
                    metadata=json.loads(row["metadata_json"]),
                )
                for row in entity_rows
            ],
            relationships=[
                KnowledgeRelationship(
                    id=row["id"],
                    document_id=document_id,
                    source_id=row["source_id"],
                    target_id=row["target_id"],
                    relationship_type=row["relationship_type"],
                    source_chunk_ids=json.loads(row["source_chunk_ids_json"]),
                    confidence=row["confidence"],
                    metadata=json.loads(row["metadata_json"]),
                )
                for row in relationship_rows
            ],
            built_at=datetime.fromisoformat(build["built_at"]),
        )

    def upsert(
        self,
        *,
        document_id: UUID,
        entities: list[KnowledgeEntity],
        relationships: list[KnowledgeRelationship],
    ) -> None:
        """Add or update enriched nodes without rebuilding deterministic nodes."""
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO knowledge_entities (
                    id, document_id, entity_type, title, description,
                    source_chunk_ids_json, confidence, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    description = excluded.description,
                    source_chunk_ids_json = excluded.source_chunk_ids_json,
                    confidence = excluded.confidence,
                    metadata_json = excluded.metadata_json
                """,
                [
                    (
                        entity.id,
                        str(document_id),
                        entity.entity_type.value,
                        entity.title,
                        entity.description,
                        json.dumps(entity.source_chunk_ids),
                        entity.confidence,
                        json.dumps(entity.metadata, sort_keys=True),
                    )
                    for entity in entities
                ],
            )
            connection.executemany(
                """
                INSERT INTO knowledge_relationships (
                    id, document_id, source_id, target_id, relationship_type,
                    source_chunk_ids_json, confidence, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    source_chunk_ids_json = excluded.source_chunk_ids_json,
                    confidence = excluded.confidence,
                    metadata_json = excluded.metadata_json
                """,
                [
                    (
                        relationship.id,
                        str(document_id),
                        relationship.source_id,
                        relationship.target_id,
                        relationship.relationship_type.value,
                        json.dumps(relationship.source_chunk_ids),
                        relationship.confidence,
                        json.dumps(relationship.metadata, sort_keys=True),
                    )
                    for relationship in relationships
                ],
            )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_builds (
                    document_id TEXT PRIMARY KEY,
                    built_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS knowledge_entities (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    source_chunk_ids_json TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_knowledge_entities_document
                    ON knowledge_entities(document_id);

                CREATE TABLE IF NOT EXISTS knowledge_relationships (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relationship_type TEXT NOT NULL,
                    source_chunk_ids_json TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    FOREIGN KEY(source_id) REFERENCES knowledge_entities(id),
                    FOREIGN KEY(target_id) REFERENCES knowledge_entities(id)
                );

                CREATE INDEX IF NOT EXISTS idx_knowledge_relationships_document
                    ON knowledge_relationships(document_id);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection
