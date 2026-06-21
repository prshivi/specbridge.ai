from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import UUID

from app.models.conflict_detection import (
    ConflictDetectionAgentResult,
    DetectedConflict,
)


class FrameworkConflictStore:
    """Normalized SQLite storage for framework conflict results and links."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def replace(self, result: ConflictDetectionAgentResult) -> None:
        document_id = str(result.document_id)
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM conflict_requirement_links WHERE document_id = ?",
                (document_id,),
            )
            connection.execute(
                "DELETE FROM conflict_business_rule_links WHERE document_id = ?",
                (document_id,),
            )
            connection.execute(
                "DELETE FROM detected_conflicts WHERE document_id = ?",
                (document_id,),
            )
            connection.executemany(
                """
                INSERT INTO detected_conflicts (
                    document_id, conflict_id, title, conflict_type, description,
                    severity, confidence, evidence_texts_json,
                    source_chunk_ids_json, source_sections_json, why_it_matters,
                    recommended_resolution_question, recommended_stakeholder,
                    blocking_for_development
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        document_id,
                        conflict.conflict_id,
                        conflict.title,
                        conflict.conflict_type.value,
                        conflict.description,
                        conflict.severity.value,
                        conflict.confidence,
                        json.dumps(conflict.evidence_texts),
                        json.dumps(conflict.source_chunk_ids),
                        json.dumps(conflict.source_sections),
                        conflict.why_it_matters,
                        conflict.recommended_resolution_question,
                        conflict.recommended_stakeholder.value,
                        int(conflict.blocking_for_development),
                    )
                    for conflict in result.conflicts
                ],
            )
            connection.executemany(
                """
                INSERT INTO conflict_requirement_links (
                    document_id, conflict_id, requirement_id
                ) VALUES (?, ?, ?)
                """,
                [
                    (document_id, conflict.conflict_id, requirement_id)
                    for conflict in result.conflicts
                    for requirement_id in conflict.involved_requirement_ids
                ],
            )
            connection.executemany(
                """
                INSERT INTO conflict_business_rule_links (
                    document_id, conflict_id, business_rule_id
                ) VALUES (?, ?, ?)
                """,
                [
                    (document_id, conflict.conflict_id, business_rule_id)
                    for conflict in result.conflicts
                    for business_rule_id in conflict.involved_business_rule_ids
                ],
            )
            connection.execute(
                """
                INSERT INTO conflict_detection_runs (
                    document_id, source_fingerprint, model, agent_version,
                    execution_time_ms, analyzed_at, knowledge_graph_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    source_fingerprint = excluded.source_fingerprint,
                    model = excluded.model,
                    agent_version = excluded.agent_version,
                    execution_time_ms = excluded.execution_time_ms,
                    analyzed_at = excluded.analyzed_at,
                    knowledge_graph_updated = excluded.knowledge_graph_updated
                """,
                (
                    document_id,
                    result.source_fingerprint,
                    result.model,
                    result.agent_version,
                    result.execution_time_ms,
                    result.analyzed_at.isoformat(),
                    int(result.knowledge_graph_updated),
                ),
            )

    def get_result(self, document_id: UUID) -> ConflictDetectionAgentResult | None:
        with self._connect() as connection:
            run = connection.execute(
                "SELECT * FROM conflict_detection_runs WHERE document_id = ?",
                (str(document_id),),
            ).fetchone()
        if run is None:
            return None
        return ConflictDetectionAgentResult(
            document_id=document_id,
            conflicts=self.list(document_id),
            cached=True,
            model=run["model"],
            agent_version=run["agent_version"],
            source_fingerprint=run["source_fingerprint"],
            execution_time_ms=0.0,
            analyzed_at=datetime.fromisoformat(run["analyzed_at"]),
            knowledge_graph_updated=bool(run["knowledge_graph_updated"]),
        )

    def get_for_fingerprint(
        self,
        *,
        document_id: UUID,
        source_fingerprint: str,
        model: str,
        agent_version: str,
    ) -> ConflictDetectionAgentResult | None:
        result = self.get_result(document_id)
        if (
            result is None
            or result.source_fingerprint != source_fingerprint
            or result.model != model
            or result.agent_version != agent_version
        ):
            return None
        return result

    def list(self, document_id: UUID) -> list[DetectedConflict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM detected_conflicts
                WHERE document_id = ?
                ORDER BY conflict_id
                """,
                (str(document_id),),
            ).fetchall()
            requirement_links = connection.execute(
                """
                SELECT conflict_id, requirement_id
                FROM conflict_requirement_links
                WHERE document_id = ?
                ORDER BY requirement_id
                """,
                (str(document_id),),
            ).fetchall()
            business_rule_links = connection.execute(
                """
                SELECT conflict_id, business_rule_id
                FROM conflict_business_rule_links
                WHERE document_id = ?
                ORDER BY business_rule_id
                """,
                (str(document_id),),
            ).fetchall()
        requirements: dict[str, list[str]] = {}
        rules: dict[str, list[str]] = {}
        for row in requirement_links:
            requirements.setdefault(row["conflict_id"], []).append(
                row["requirement_id"]
            )
        for row in business_rule_links:
            rules.setdefault(row["conflict_id"], []).append(row["business_rule_id"])
        return [
            self._to_conflict(
                row,
                requirements.get(row["conflict_id"], []),
                rules.get(row["conflict_id"], []),
            )
            for row in rows
        ]

    def get(self, document_id: UUID, conflict_id: str) -> DetectedConflict | None:
        return next(
            (
                conflict
                for conflict in self.list(document_id)
                if conflict.conflict_id == conflict_id
            ),
            None,
        )

    @staticmethod
    def _to_conflict(
        row: sqlite3.Row,
        requirement_ids: list[str],
        business_rule_ids: list[str],
    ) -> DetectedConflict:
        return DetectedConflict(
            conflict_id=row["conflict_id"],
            title=row["title"],
            conflict_type=row["conflict_type"],
            description=row["description"],
            severity=row["severity"],
            confidence=row["confidence"],
            involved_requirement_ids=requirement_ids,
            involved_business_rule_ids=business_rule_ids,
            evidence_texts=json.loads(row["evidence_texts_json"]),
            source_chunk_ids=json.loads(row["source_chunk_ids_json"]),
            source_sections=json.loads(row["source_sections_json"]),
            why_it_matters=row["why_it_matters"],
            recommended_resolution_question=row[
                "recommended_resolution_question"
            ],
            recommended_stakeholder=row["recommended_stakeholder"],
            blocking_for_development=bool(row["blocking_for_development"]),
        )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conflict_detection_runs (
                    document_id TEXT PRIMARY KEY,
                    source_fingerprint TEXT NOT NULL,
                    model TEXT NOT NULL,
                    agent_version TEXT NOT NULL,
                    execution_time_ms REAL NOT NULL,
                    analyzed_at TEXT NOT NULL,
                    knowledge_graph_updated INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS detected_conflicts (
                    document_id TEXT NOT NULL,
                    conflict_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    conflict_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    evidence_texts_json TEXT NOT NULL,
                    source_chunk_ids_json TEXT NOT NULL,
                    source_sections_json TEXT NOT NULL,
                    why_it_matters TEXT NOT NULL,
                    recommended_resolution_question TEXT NOT NULL,
                    recommended_stakeholder TEXT NOT NULL,
                    blocking_for_development INTEGER NOT NULL,
                    PRIMARY KEY(document_id, conflict_id)
                );

                CREATE TABLE IF NOT EXISTS conflict_requirement_links (
                    document_id TEXT NOT NULL,
                    conflict_id TEXT NOT NULL,
                    requirement_id TEXT NOT NULL,
                    PRIMARY KEY(document_id, conflict_id, requirement_id)
                );

                CREATE TABLE IF NOT EXISTS conflict_business_rule_links (
                    document_id TEXT NOT NULL,
                    conflict_id TEXT NOT NULL,
                    business_rule_id TEXT NOT NULL,
                    PRIMARY KEY(document_id, conflict_id, business_rule_id)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection
