from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import UUID

from app.models.engineering_blueprint import (
    BlueprintArtifact,
    EngineeringArtifactType,
    EngineeringBlueprintResult,
    RequirementEngineeringBlueprint,
)


class EngineeringBlueprintStore:
    """Normalized SQLite persistence for framework engineering artifacts."""

    _LINKS = {
        "assumption": "engineering_artifact_assumption_links",
        "ambiguity": "engineering_artifact_ambiguity_links",
        "conflict": "engineering_artifact_conflict_links",
        "missing_requirement": "engineering_artifact_missing_requirement_links",
    }

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def replace(self, result: EngineeringBlueprintResult) -> None:
        document_id = str(result.document_id)
        artifacts = [
            artifact
            for blueprint in result.requirement_blueprints
            for artifact in blueprint.artifacts
        ]
        with self._connect() as connection:
            for table in (
                *self._LINKS.values(),
                "engineering_blueprint_artifacts",
                "engineering_blueprint_requirements",
            ):
                connection.execute(
                    f"DELETE FROM {table} WHERE document_id = ?",
                    (document_id,),
                )
            connection.executemany(
                """
                INSERT INTO engineering_blueprint_requirements (
                    document_id, requirement_id, requirement_title
                ) VALUES (?, ?, ?)
                """,
                [
                    (
                        document_id,
                        blueprint.requirement_id,
                        blueprint.requirement_title,
                    )
                    for blueprint in result.requirement_blueprints
                ],
            )
            connection.executemany(
                """
                INSERT INTO engineering_blueprint_artifacts (
                    document_id, artifact_id, requirement_id, artifact_type,
                    title, description, provenance, confidence, evidence_text,
                    suggestion_reason, source_chunk_ids_json,
                    source_sections_json, traceability_score, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        document_id,
                        item.artifact_id,
                        item.requirement_id,
                        item.artifact_type.value,
                        item.title,
                        item.description,
                        item.provenance.value,
                        item.confidence,
                        item.evidence_text,
                        item.suggestion_reason,
                        json.dumps(item.source_chunk_ids),
                        json.dumps(item.source_sections),
                        item.traceability_score,
                        item.payload.model_dump_json(),
                    )
                    for item in artifacts
                ],
            )
            for name, attribute in (
                ("assumption", "related_assumption_ids"),
                ("ambiguity", "related_ambiguity_ids"),
                ("conflict", "related_conflict_ids"),
                (
                    "missing_requirement",
                    "related_missing_requirement_ids",
                ),
            ):
                self._write_links(
                    connection,
                    document_id,
                    name,
                    {
                        item.artifact_id: getattr(item, attribute)
                        for item in artifacts
                    },
                )
            connection.execute(
                """
                INSERT INTO engineering_blueprint_runs (
                    document_id, source_fingerprint, model, agent_version,
                    execution_time_ms, generated_at, knowledge_graph_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    source_fingerprint = excluded.source_fingerprint,
                    model = excluded.model,
                    agent_version = excluded.agent_version,
                    execution_time_ms = excluded.execution_time_ms,
                    generated_at = excluded.generated_at,
                    knowledge_graph_updated = excluded.knowledge_graph_updated
                """,
                (
                    document_id,
                    result.source_fingerprint,
                    result.model,
                    result.agent_version,
                    result.execution_time_ms,
                    result.generated_at.isoformat(),
                    int(result.knowledge_graph_updated),
                ),
            )

    def get_result(self, document_id: UUID) -> EngineeringBlueprintResult | None:
        with self._connect() as connection:
            run = connection.execute(
                "SELECT * FROM engineering_blueprint_runs WHERE document_id = ?",
                (str(document_id),),
            ).fetchone()
            requirement_rows = connection.execute(
                """
                SELECT * FROM engineering_blueprint_requirements
                WHERE document_id = ? ORDER BY requirement_id
                """,
                (str(document_id),),
            ).fetchall()
        if run is None:
            return None
        artifacts = self.list_artifacts(document_id)
        by_requirement: dict[str, list[BlueprintArtifact]] = {}
        for artifact in artifacts:
            by_requirement.setdefault(artifact.requirement_id, []).append(artifact)
        blueprints = [
            RequirementEngineeringBlueprint(
                requirement_id=row["requirement_id"],
                requirement_title=row["requirement_title"],
                artifacts=by_requirement.get(row["requirement_id"], []),
            )
            for row in requirement_rows
        ]
        return EngineeringBlueprintResult(
            document_id=document_id,
            requirement_blueprints=blueprints,
            total_requirements=len(blueprints),
            total_artifacts=len(artifacts),
            clarification_artifacts=sum(
                item.artifact_type is EngineeringArtifactType.OPEN_QUESTION
                for item in artifacts
            ),
            cached=True,
            model=run["model"],
            agent_version=run["agent_version"],
            source_fingerprint=run["source_fingerprint"],
            execution_time_ms=0.0,
            generated_at=datetime.fromisoformat(run["generated_at"]),
            knowledge_graph_updated=bool(run["knowledge_graph_updated"]),
        )

    def get_for_fingerprint(
        self,
        *,
        document_id: UUID,
        source_fingerprint: str,
        model: str,
        agent_version: str,
    ) -> EngineeringBlueprintResult | None:
        result = self.get_result(document_id)
        if (
            result is None
            or result.source_fingerprint != source_fingerprint
            or result.model != model
            or result.agent_version != agent_version
        ):
            return None
        return result

    def list_artifacts(self, document_id: UUID) -> list[BlueprintArtifact]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM engineering_blueprint_artifacts
                WHERE document_id = ? ORDER BY artifact_id
                """,
                (str(document_id),),
            ).fetchall()
            links = {
                name: self._read_links(connection, document_id, name)
                for name in self._LINKS
            }
        return [
            BlueprintArtifact(
                artifact_id=row["artifact_id"],
                requirement_id=row["requirement_id"],
                artifact_type=row["artifact_type"],
                title=row["title"],
                description=row["description"],
                provenance=row["provenance"],
                confidence=row["confidence"],
                evidence_text=row["evidence_text"],
                suggestion_reason=row["suggestion_reason"],
                source_chunk_ids=json.loads(row["source_chunk_ids_json"]),
                source_sections=json.loads(row["source_sections_json"]),
                related_assumption_ids=links["assumption"].get(
                    row["artifact_id"], []
                ),
                related_ambiguity_ids=links["ambiguity"].get(
                    row["artifact_id"], []
                ),
                related_conflict_ids=links["conflict"].get(
                    row["artifact_id"], []
                ),
                related_missing_requirement_ids=links[
                    "missing_requirement"
                ].get(row["artifact_id"], []),
                traceability_score=row["traceability_score"],
                payload=json.loads(row["payload_json"]),
            )
            for row in rows
        ]

    def get(
        self,
        document_id: UUID,
        artifact_id: str,
    ) -> BlueprintArtifact | None:
        return next(
            (
                artifact
                for artifact in self.list_artifacts(document_id)
                if artifact.artifact_id == artifact_id
            ),
            None,
        )

    def _write_links(
        self,
        connection: sqlite3.Connection,
        document_id: str,
        name: str,
        values: dict[str, list[str]],
    ) -> None:
        table = self._LINKS[name]
        column = f"{name}_id"
        connection.executemany(
            f"""
            INSERT INTO {table} (document_id, artifact_id, {column})
            VALUES (?, ?, ?)
            """,
            [
                (document_id, artifact_id, target_id)
                for artifact_id, target_ids in values.items()
                for target_id in target_ids
            ],
        )

    def _read_links(
        self,
        connection: sqlite3.Connection,
        document_id: UUID,
        name: str,
    ) -> dict[str, list[str]]:
        table = self._LINKS[name]
        column = f"{name}_id"
        rows = connection.execute(
            f"""
            SELECT artifact_id, {column} FROM {table}
            WHERE document_id = ? ORDER BY {column}
            """,
            (str(document_id),),
        ).fetchall()
        result: dict[str, list[str]] = {}
        for row in rows:
            result.setdefault(row["artifact_id"], []).append(row[column])
        return result

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS engineering_blueprint_runs (
                    document_id TEXT PRIMARY KEY,
                    source_fingerprint TEXT NOT NULL,
                    model TEXT NOT NULL,
                    agent_version TEXT NOT NULL,
                    execution_time_ms REAL NOT NULL,
                    generated_at TEXT NOT NULL,
                    knowledge_graph_updated INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS engineering_blueprint_requirements (
                    document_id TEXT NOT NULL,
                    requirement_id TEXT NOT NULL,
                    requirement_title TEXT NOT NULL,
                    PRIMARY KEY(document_id, requirement_id)
                );
                CREATE TABLE IF NOT EXISTS engineering_blueprint_artifacts (
                    document_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    requirement_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    provenance TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    evidence_text TEXT,
                    suggestion_reason TEXT,
                    source_chunk_ids_json TEXT NOT NULL,
                    source_sections_json TEXT NOT NULL,
                    traceability_score REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY(document_id, artifact_id)
                );
                CREATE TABLE IF NOT EXISTS engineering_artifact_assumption_links (
                    document_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    assumption_id TEXT NOT NULL,
                    PRIMARY KEY(document_id, artifact_id, assumption_id)
                );
                CREATE TABLE IF NOT EXISTS engineering_artifact_ambiguity_links (
                    document_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    ambiguity_id TEXT NOT NULL,
                    PRIMARY KEY(document_id, artifact_id, ambiguity_id)
                );
                CREATE TABLE IF NOT EXISTS engineering_artifact_conflict_links (
                    document_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    conflict_id TEXT NOT NULL,
                    PRIMARY KEY(document_id, artifact_id, conflict_id)
                );
                CREATE TABLE IF NOT EXISTS engineering_artifact_missing_requirement_links (
                    document_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    missing_requirement_id TEXT NOT NULL,
                    PRIMARY KEY(
                        document_id, artifact_id, missing_requirement_id
                    )
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection
