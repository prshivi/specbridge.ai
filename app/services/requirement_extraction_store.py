import json
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import UUID

from app.models.requirement_extraction import (
    ExtractedRequirement,
    RequirementExtractionResult,
)


class RequirementExtractionStore:
    """Normalized SQLite persistence for framework-extracted requirements."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def replace(self, result: RequirementExtractionResult) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM extracted_requirements WHERE document_id = ?",
                (str(result.document_id),),
            )
            connection.executemany(
                """
                INSERT INTO extracted_requirements (
                    document_id, requirement_id, title, description, category,
                    priority, confidence, source_chunk_ids_json, source_section,
                    evidence_text, explicit_or_inferred, ambiguity_flag,
                    missing_info_flag
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(result.document_id),
                        requirement.requirement_id,
                        requirement.title,
                        requirement.description,
                        requirement.category.value,
                        requirement.priority.value,
                        requirement.confidence,
                        json.dumps(requirement.source_chunk_ids),
                        requirement.source_section,
                        requirement.evidence_text,
                        requirement.explicit_or_inferred.value,
                        int(requirement.ambiguity_flag),
                        int(requirement.missing_info_flag),
                    )
                    for requirement in result.requirements
                ],
            )
            connection.execute(
                """
                INSERT INTO requirement_extraction_runs (
                    document_id, source_fingerprint, model, agent_version,
                    execution_time_ms, extracted_at, knowledge_graph_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    source_fingerprint = excluded.source_fingerprint,
                    model = excluded.model,
                    agent_version = excluded.agent_version,
                    execution_time_ms = excluded.execution_time_ms,
                    extracted_at = excluded.extracted_at,
                    knowledge_graph_updated = excluded.knowledge_graph_updated
                """,
                (
                    str(result.document_id),
                    result.source_fingerprint,
                    result.model,
                    result.agent_version,
                    result.execution_time_ms,
                    result.extracted_at.isoformat(),
                    int(result.knowledge_graph_updated),
                ),
            )

    def get_result(self, document_id: UUID) -> RequirementExtractionResult | None:
        with self._connect() as connection:
            run = connection.execute(
                """
                SELECT * FROM requirement_extraction_runs
                WHERE document_id = ?
                """,
                (str(document_id),),
            ).fetchone()
        if run is None:
            return None
        return RequirementExtractionResult(
            document_id=document_id,
            requirements=self.list(document_id),
            cached=True,
            model=run["model"],
            agent_version=run["agent_version"],
            source_fingerprint=run["source_fingerprint"],
            execution_time_ms=0.0,
            extracted_at=datetime.fromisoformat(run["extracted_at"]),
            knowledge_graph_updated=bool(run["knowledge_graph_updated"]),
        )

    def get_for_fingerprint(
        self,
        *,
        document_id: UUID,
        source_fingerprint: str,
        model: str,
        agent_version: str,
    ) -> RequirementExtractionResult | None:
        result = self.get_result(document_id)
        if (
            result is None
            or result.source_fingerprint != source_fingerprint
            or result.model != model
            or result.agent_version != agent_version
        ):
            return None
        return result

    def list(self, document_id: UUID) -> list[ExtractedRequirement]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM extracted_requirements
                WHERE document_id = ?
                ORDER BY requirement_id
                """,
                (str(document_id),),
            ).fetchall()
        return [self._to_requirement(row) for row in rows]

    def get(
        self,
        document_id: UUID,
        requirement_id: str,
    ) -> ExtractedRequirement | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM extracted_requirements
                WHERE document_id = ? AND requirement_id = ?
                """,
                (str(document_id), requirement_id),
            ).fetchone()
        return self._to_requirement(row) if row is not None else None

    @staticmethod
    def _to_requirement(row: sqlite3.Row) -> ExtractedRequirement:
        return ExtractedRequirement(
            requirement_id=row["requirement_id"],
            title=row["title"],
            description=row["description"],
            category=row["category"],
            priority=row["priority"],
            confidence=row["confidence"],
            source_chunk_ids=json.loads(row["source_chunk_ids_json"]),
            source_section=row["source_section"],
            evidence_text=row["evidence_text"],
            explicit_or_inferred=row["explicit_or_inferred"],
            ambiguity_flag=bool(row["ambiguity_flag"]),
            missing_info_flag=bool(row["missing_info_flag"]),
        )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS requirement_extraction_runs (
                    document_id TEXT PRIMARY KEY,
                    source_fingerprint TEXT NOT NULL,
                    model TEXT NOT NULL,
                    agent_version TEXT NOT NULL,
                    execution_time_ms REAL NOT NULL,
                    extracted_at TEXT NOT NULL,
                    knowledge_graph_updated INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS extracted_requirements (
                    document_id TEXT NOT NULL,
                    requirement_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    category TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    source_chunk_ids_json TEXT NOT NULL,
                    source_section TEXT NOT NULL,
                    evidence_text TEXT NOT NULL,
                    explicit_or_inferred TEXT NOT NULL,
                    ambiguity_flag INTEGER NOT NULL,
                    missing_info_flag INTEGER NOT NULL,
                    PRIMARY KEY(document_id, requirement_id)
                );

                CREATE INDEX IF NOT EXISTS idx_extracted_requirements_document
                ON extracted_requirements(document_id);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection
