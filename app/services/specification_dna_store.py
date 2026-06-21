import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import UUID

from app.models.specification_dna import SpecificationDNA, SpecificationDNAResult


class SpecificationDNAStore:
    """Canonical SQLite persistence for Specification DNA."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def get(
        self,
        *,
        document_id: UUID,
        source_fingerprint: str,
        model: str,
        agent_version: str,
    ) -> SpecificationDNAResult | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT dna_json, execution_time_ms, generated_at
                FROM specification_dna
                WHERE document_id = ?
                  AND source_fingerprint = ?
                  AND model = ?
                  AND agent_version = ?
                """,
                (
                    str(document_id),
                    source_fingerprint,
                    model,
                    agent_version,
                ),
            ).fetchone()
        if row is None:
            return None
        return SpecificationDNAResult(
            document_id=document_id,
            specification_dna=SpecificationDNA.model_validate_json(row["dna_json"]),
            cached=True,
            model=model,
            agent_version=agent_version,
            source_fingerprint=source_fingerprint,
            execution_time_ms=0.0,
            generated_at=datetime.fromisoformat(row["generated_at"]),
        )

    def set(self, result: SpecificationDNAResult) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO specification_dna (
                    document_id, source_fingerprint, model, agent_version,
                    dna_json, execution_time_ms, generated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    source_fingerprint = excluded.source_fingerprint,
                    model = excluded.model,
                    agent_version = excluded.agent_version,
                    dna_json = excluded.dna_json,
                    execution_time_ms = excluded.execution_time_ms,
                    generated_at = excluded.generated_at
                """,
                (
                    str(result.document_id),
                    result.source_fingerprint,
                    result.model,
                    result.agent_version,
                    result.specification_dna.model_dump_json(),
                    result.execution_time_ms,
                    result.generated_at.isoformat(),
                ),
            )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS specification_dna (
                    document_id TEXT PRIMARY KEY,
                    source_fingerprint TEXT NOT NULL,
                    model TEXT NOT NULL,
                    agent_version TEXT NOT NULL,
                    dna_json TEXT NOT NULL,
                    execution_time_ms REAL NOT NULL,
                    generated_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection
