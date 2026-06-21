import sqlite3
from pathlib import Path

from app.models.copilot import DeveloperCopilotResponse


class DeveloperCopilotStore:
    """SQLite history for developer copilot interactions."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def add(self, response: DeveloperCopilotResponse) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO developer_copilot_interactions (
                    interaction_id,
                    document_id,
                    question,
                    result_json,
                    answered_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    response.interaction_id,
                    str(response.document_id),
                    response.question,
                    response.model_dump_json(),
                    response.answered_at.isoformat(),
                ),
            )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS developer_copilot_interactions (
                    interaction_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    answered_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_copilot_document
                ON developer_copilot_interactions(document_id, answered_at)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection
