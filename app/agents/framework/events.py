import json
import sqlite3
from pathlib import Path
from typing import Protocol

from app.agents.framework.models import AgentEvent


class AgentEventLogger(Protocol):
    def log(self, event: AgentEvent) -> None:
        """Persist one lifecycle event."""


class NullAgentEventLogger:
    def log(self, event: AgentEvent) -> None:
        del event


class InMemoryAgentEventLogger:
    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    def log(self, event: AgentEvent) -> None:
        self.events.append(event)


class SQLiteAgentEventLogger:
    """Durable lifecycle and warning log for agent executions."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def log(self, event: AgentEvent) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_events (
                    event_type, agent_name, timestamp, duration_ms,
                    message, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_type.value,
                    event.agent_name,
                    event.timestamp.isoformat(),
                    event.duration_ms,
                    event.message,
                    json.dumps(event.metadata, sort_keys=True, default=str),
                ),
            )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    duration_ms REAL,
                    message TEXT,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agent_events_agent_timestamp
                ON agent_events(agent_name, timestamp)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection
