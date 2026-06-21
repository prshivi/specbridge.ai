import sqlite3
from pathlib import Path

from app.agents.framework.models import AgentResult


class AgentResultCache:
    """SQLite cache keyed by agent version and Specification DNA fingerprint."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def get(
        self,
        *,
        agent_name: str,
        agent_version: str,
        dna_fingerprint: str,
    ) -> AgentResult | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT result_json
                FROM agent_result_cache
                WHERE agent_name = ?
                  AND agent_version = ?
                  AND dna_fingerprint = ?
                """,
                (agent_name, agent_version, dna_fingerprint),
            ).fetchone()
        if row is None:
            return None
        result = AgentResult.model_validate_json(row["result_json"])
        return result.model_copy(update={"cached": True, "execution_time_ms": 0.0})

    def set(
        self,
        *,
        agent_name: str,
        agent_version: str,
        dna_fingerprint: str,
        result: AgentResult,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_result_cache (
                    agent_name, agent_version, dna_fingerprint, result_json
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(agent_name, agent_version, dna_fingerprint)
                DO UPDATE SET result_json = excluded.result_json
                """,
                (
                    agent_name,
                    agent_version,
                    dna_fingerprint,
                    result.model_copy(update={"cached": False}).model_dump_json(),
                ),
            )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_result_cache (
                    agent_name TEXT NOT NULL,
                    agent_version TEXT NOT NULL,
                    dna_fingerprint TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    PRIMARY KEY(agent_name, agent_version, dna_fingerprint)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection
