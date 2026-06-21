import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import UUID

from app.models.architecture_blueprint import (
    ArchitectureBlueprint,
    ArchitectureBlueprintResult,
    ArchitectureDiagram,
    ArchitectureDiagramCollection,
)


class ArchitectureBlueprintStore:
    """SQLite persistence for framework Architecture Blueprints."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def set(self, result: ArchitectureBlueprintResult) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO architecture_blueprints (
                    document_id, source_fingerprint, model, agent_version,
                    execution_time_ms, generated_at, knowledge_graph_updated,
                    architecture_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    source_fingerprint = excluded.source_fingerprint,
                    model = excluded.model,
                    agent_version = excluded.agent_version,
                    execution_time_ms = excluded.execution_time_ms,
                    generated_at = excluded.generated_at,
                    knowledge_graph_updated = excluded.knowledge_graph_updated,
                    architecture_json = excluded.architecture_json
                """,
                (
                    str(result.document_id),
                    result.source_fingerprint,
                    result.model,
                    result.agent_version,
                    result.execution_time_ms,
                    result.generated_at.isoformat(),
                    int(result.knowledge_graph_updated),
                    result.architecture.model_dump_json(),
                ),
            )

    def get(self, document_id: UUID) -> ArchitectureBlueprintResult | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM architecture_blueprints WHERE document_id = ?",
                (str(document_id),),
            ).fetchone()
        if row is None:
            return None
        architecture = ArchitectureBlueprint.model_validate_json(
            row["architecture_json"]
        )
        return ArchitectureBlueprintResult(
            document_id=document_id,
            architecture=architecture,
            total_recommendations=len(architecture.recommendations),
            total_diagrams=len(architecture.diagrams),
            clarification_recommendations=sum(
                item.provenance.value == "needs_clarification"
                for item in architecture.recommendations
            ),
            cached=True,
            model=row["model"],
            agent_version=row["agent_version"],
            source_fingerprint=row["source_fingerprint"],
            execution_time_ms=0.0,
            generated_at=datetime.fromisoformat(row["generated_at"]),
            knowledge_graph_updated=bool(row["knowledge_graph_updated"]),
        )

    def get_for_fingerprint(
        self,
        *,
        document_id: UUID,
        source_fingerprint: str,
        model: str,
        agent_version: str,
    ) -> ArchitectureBlueprintResult | None:
        result = self.get(document_id)
        if (
            result is None
            or result.source_fingerprint != source_fingerprint
            or result.model != model
            or result.agent_version != agent_version
        ):
            return None
        return result

    def diagrams(
        self,
        document_id: UUID,
    ) -> ArchitectureDiagramCollection | None:
        result = self.get(document_id)
        if result is None:
            return None
        return ArchitectureDiagramCollection(
            document_id=document_id,
            diagrams=[
                ArchitectureDiagram.model_validate(item)
                for item in result.architecture.diagrams
            ],
        )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS architecture_blueprints (
                    document_id TEXT PRIMARY KEY,
                    source_fingerprint TEXT NOT NULL,
                    model TEXT NOT NULL,
                    agent_version TEXT NOT NULL,
                    execution_time_ms REAL NOT NULL,
                    generated_at TEXT NOT NULL,
                    knowledge_graph_updated INTEGER NOT NULL,
                    architecture_json TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection
