from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import UUID

from app.models.missing_requirements import (
    MissingRequirementDetectionResult,
    MissingRequirementIssue,
)


class MissingRequirementStore:
    """Normalized SQLite persistence for contextual requirement gaps."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def replace(
        self,
        result: MissingRequirementDetectionResult,
        *,
        integration_links: dict[str, list[str]] | None = None,
    ) -> None:
        document_id = str(result.document_id)
        integration_links = integration_links or {}
        with self._connect() as connection:
            for table in (
                "missing_requirement_requirement_links",
                "missing_requirement_workflow_links",
                "missing_requirement_actor_links",
                "missing_requirement_integration_links",
                "missing_requirement_issues",
            ):
                connection.execute(
                    f"DELETE FROM {table} WHERE document_id = ?",
                    (document_id,),
                )
            connection.executemany(
                """
                INSERT INTO missing_requirement_issues (
                    document_id, missing_requirement_id, title, gap_type,
                    description, severity, confidence, source_chunk_ids_json,
                    source_sections_json, why_it_matters,
                    suggested_requirement_text, clarification_question,
                    recommended_stakeholder, blocking_for_development,
                    explicit_gap_or_inferred_gap
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        document_id,
                        issue.missing_requirement_id,
                        issue.title,
                        issue.gap_type.value,
                        issue.description,
                        issue.severity.value,
                        issue.confidence,
                        json.dumps(issue.source_chunk_ids),
                        json.dumps(issue.source_sections),
                        issue.why_it_matters,
                        issue.suggested_requirement_text,
                        issue.clarification_question,
                        issue.recommended_stakeholder.value,
                        int(issue.blocking_for_development),
                        issue.explicit_gap_or_inferred_gap.value,
                    )
                    for issue in result.missing_requirements
                ],
            )
            self._insert_links(
                connection,
                "missing_requirement_requirement_links",
                "requirement_id",
                document_id,
                {
                    issue.missing_requirement_id: issue.related_requirement_ids
                    for issue in result.missing_requirements
                },
            )
            self._insert_links(
                connection,
                "missing_requirement_workflow_links",
                "workflow_id",
                document_id,
                {
                    issue.missing_requirement_id: issue.related_workflow_ids
                    for issue in result.missing_requirements
                },
            )
            self._insert_links(
                connection,
                "missing_requirement_actor_links",
                "actor_id",
                document_id,
                {
                    issue.missing_requirement_id: issue.related_actor_ids
                    for issue in result.missing_requirements
                },
            )
            self._insert_links(
                connection,
                "missing_requirement_integration_links",
                "integration_id",
                document_id,
                integration_links,
            )
            connection.execute(
                """
                INSERT INTO missing_requirement_runs (
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

    @staticmethod
    def _insert_links(
        connection: sqlite3.Connection,
        table: str,
        id_column: str,
        document_id: str,
        links: dict[str, list[str]],
    ) -> None:
        connection.executemany(
            f"""
            INSERT INTO {table} (
                document_id, missing_requirement_id, {id_column}
            ) VALUES (?, ?, ?)
            """,
            [
                (document_id, issue_id, target_id)
                for issue_id, target_ids in links.items()
                for target_id in target_ids
            ],
        )

    def get_result(
        self,
        document_id: UUID,
    ) -> MissingRequirementDetectionResult | None:
        with self._connect() as connection:
            run = connection.execute(
                "SELECT * FROM missing_requirement_runs WHERE document_id = ?",
                (str(document_id),),
            ).fetchone()
        if run is None:
            return None
        return MissingRequirementDetectionResult(
            document_id=document_id,
            missing_requirements=self.list(document_id),
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
    ) -> MissingRequirementDetectionResult | None:
        result = self.get_result(document_id)
        if (
            result is None
            or result.source_fingerprint != source_fingerprint
            or result.model != model
            or result.agent_version != agent_version
        ):
            return None
        return result

    def list(self, document_id: UUID) -> list[MissingRequirementIssue]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM missing_requirement_issues
                WHERE document_id = ?
                ORDER BY missing_requirement_id
                """,
                (str(document_id),),
            ).fetchall()
            requirements = self._read_links(
                connection,
                "missing_requirement_requirement_links",
                "requirement_id",
                document_id,
            )
            workflows = self._read_links(
                connection,
                "missing_requirement_workflow_links",
                "workflow_id",
                document_id,
            )
            actors = self._read_links(
                connection,
                "missing_requirement_actor_links",
                "actor_id",
                document_id,
            )
        return [
            MissingRequirementIssue(
                missing_requirement_id=row["missing_requirement_id"],
                title=row["title"],
                gap_type=row["gap_type"],
                description=row["description"],
                severity=row["severity"],
                confidence=row["confidence"],
                related_requirement_ids=requirements.get(
                    row["missing_requirement_id"], []
                ),
                related_workflow_ids=workflows.get(
                    row["missing_requirement_id"], []
                ),
                related_actor_ids=actors.get(row["missing_requirement_id"], []),
                source_chunk_ids=json.loads(row["source_chunk_ids_json"]),
                source_sections=json.loads(row["source_sections_json"]),
                why_it_matters=row["why_it_matters"],
                suggested_requirement_text=row["suggested_requirement_text"],
                clarification_question=row["clarification_question"],
                recommended_stakeholder=row["recommended_stakeholder"],
                blocking_for_development=bool(row["blocking_for_development"]),
                explicit_gap_or_inferred_gap=row[
                    "explicit_gap_or_inferred_gap"
                ],
            )
            for row in rows
        ]

    @staticmethod
    def _read_links(
        connection: sqlite3.Connection,
        table: str,
        id_column: str,
        document_id: UUID,
    ) -> dict[str, list[str]]:
        rows = connection.execute(
            f"""
            SELECT missing_requirement_id, {id_column}
            FROM {table}
            WHERE document_id = ?
            ORDER BY {id_column}
            """,
            (str(document_id),),
        ).fetchall()
        values: dict[str, list[str]] = {}
        for row in rows:
            values.setdefault(row["missing_requirement_id"], []).append(
                row[id_column]
            )
        return values

    def get(
        self,
        document_id: UUID,
        missing_requirement_id: str,
    ) -> MissingRequirementIssue | None:
        return next(
            (
                issue
                for issue in self.list(document_id)
                if issue.missing_requirement_id == missing_requirement_id
            ),
            None,
        )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS missing_requirement_runs (
                    document_id TEXT PRIMARY KEY,
                    source_fingerprint TEXT NOT NULL,
                    model TEXT NOT NULL,
                    agent_version TEXT NOT NULL,
                    execution_time_ms REAL NOT NULL,
                    analyzed_at TEXT NOT NULL,
                    knowledge_graph_updated INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS missing_requirement_issues (
                    document_id TEXT NOT NULL,
                    missing_requirement_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    gap_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    source_chunk_ids_json TEXT NOT NULL,
                    source_sections_json TEXT NOT NULL,
                    why_it_matters TEXT NOT NULL,
                    suggested_requirement_text TEXT NOT NULL,
                    clarification_question TEXT NOT NULL,
                    recommended_stakeholder TEXT NOT NULL,
                    blocking_for_development INTEGER NOT NULL,
                    explicit_gap_or_inferred_gap TEXT NOT NULL,
                    PRIMARY KEY(document_id, missing_requirement_id)
                );

                CREATE TABLE IF NOT EXISTS missing_requirement_requirement_links (
                    document_id TEXT NOT NULL,
                    missing_requirement_id TEXT NOT NULL,
                    requirement_id TEXT NOT NULL,
                    PRIMARY KEY(document_id, missing_requirement_id, requirement_id)
                );

                CREATE TABLE IF NOT EXISTS missing_requirement_workflow_links (
                    document_id TEXT NOT NULL,
                    missing_requirement_id TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    PRIMARY KEY(document_id, missing_requirement_id, workflow_id)
                );

                CREATE TABLE IF NOT EXISTS missing_requirement_actor_links (
                    document_id TEXT NOT NULL,
                    missing_requirement_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    PRIMARY KEY(document_id, missing_requirement_id, actor_id)
                );

                CREATE TABLE IF NOT EXISTS missing_requirement_integration_links (
                    document_id TEXT NOT NULL,
                    missing_requirement_id TEXT NOT NULL,
                    integration_id TEXT NOT NULL,
                    PRIMARY KEY(document_id, missing_requirement_id, integration_id)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection
