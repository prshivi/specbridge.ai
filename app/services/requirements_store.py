import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from app.models.requirements import RequirementIntelligence


class RequirementIntelligenceStore:
    """SQLite persistence for requirement intelligence results."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def get(
        self,
        *,
        document_id: UUID,
        fingerprint: str,
        model: str,
        prompt_version: str,
    ) -> tuple[RequirementIntelligence, datetime] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT result_json, analyzed_at
                FROM requirement_intelligence
                WHERE document_id = ?
                  AND fingerprint = ?
                  AND model = ?
                  AND prompt_version = ?
                """,
                (str(document_id), fingerprint, model, prompt_version),
            ).fetchone()
        if row is None:
            return None
        return (
            RequirementIntelligence.model_validate_json(row["result_json"]),
            datetime.fromisoformat(row["analyzed_at"]),
        )

    def set(
        self,
        *,
        document_id: UUID,
        fingerprint: str,
        model: str,
        prompt_version: str,
        result: RequirementIntelligence,
        analyzed_at: datetime,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO requirement_intelligence (
                    document_id,
                    fingerprint,
                    model,
                    prompt_version,
                    result_json,
                    analyzed_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    fingerprint = excluded.fingerprint,
                    model = excluded.model,
                    prompt_version = excluded.prompt_version,
                    result_json = excluded.result_json,
                    analyzed_at = excluded.analyzed_at
                """,
                (
                    str(document_id),
                    fingerprint,
                    model,
                    prompt_version,
                    result.model_dump_json(),
                    analyzed_at.astimezone(UTC).isoformat(),
                ),
            )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS requirement_intelligence (
                    document_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    analyzed_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection
