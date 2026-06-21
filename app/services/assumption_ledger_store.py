from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import UUID

from app.models.assumption_ledger import (
    AssumptionStatus,
    FrameworkAssumptionLedgerResult,
    LedgerAssumption,
    LedgerFact,
)


class FrameworkAssumptionLedgerStore:
    """Normalized SQLite persistence for facts, assumptions, and links."""

    _LINK_TABLES = {
        "requirement": "assumption_requirement_links",
        "ambiguity": "assumption_ambiguity_links",
        "conflict": "assumption_conflict_links",
        "missing_requirement": "assumption_missing_requirement_links",
    }

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def replace(self, result: FrameworkAssumptionLedgerResult) -> None:
        document_id = str(result.document_id)
        with self._connect() as connection:
            for table in (
                *self._LINK_TABLES.values(),
                "framework_ledger_facts",
                "framework_ledger_assumptions",
            ):
                connection.execute(
                    f"DELETE FROM {table} WHERE document_id = ?",
                    (document_id,),
                )
            connection.executemany(
                """
                INSERT INTO framework_ledger_facts (
                    document_id, fact_id, title, description, evidence_text,
                    source_chunk_ids_json, source_sections_json,
                    related_requirement_ids_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        document_id,
                        fact.fact_id,
                        fact.title,
                        fact.description,
                        fact.evidence_text,
                        json.dumps(fact.source_chunk_ids),
                        json.dumps(fact.source_sections),
                        json.dumps(fact.related_requirement_ids),
                    )
                    for fact in result.facts
                ],
            )
            connection.executemany(
                """
                INSERT INTO framework_ledger_assumptions (
                    document_id, assumption_id, title, description,
                    assumption_type, confidence, reason, evidence_text,
                    source_chunk_ids_json, source_sections_json, impact_area,
                    risk_level, needs_stakeholder_confirmation,
                    confirmation_question, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        document_id,
                        item.assumption_id,
                        item.title,
                        item.description,
                        item.assumption_type.value,
                        item.confidence,
                        item.reason,
                        item.evidence_text,
                        json.dumps(item.source_chunk_ids),
                        json.dumps(item.source_sections),
                        item.impact_area.value,
                        item.risk_level.value,
                        int(item.needs_stakeholder_confirmation),
                        item.confirmation_question,
                        item.status.value,
                    )
                    for item in result.assumptions
                ],
            )
            self._write_links(
                connection,
                document_id,
                "requirement",
                {
                    item.assumption_id: item.related_requirement_ids
                    for item in result.assumptions
                },
            )
            self._write_links(
                connection,
                document_id,
                "ambiguity",
                {
                    item.assumption_id: item.related_ambiguity_ids
                    for item in result.assumptions
                },
            )
            self._write_links(
                connection,
                document_id,
                "conflict",
                {
                    item.assumption_id: item.related_conflict_ids
                    for item in result.assumptions
                },
            )
            self._write_links(
                connection,
                document_id,
                "missing_requirement",
                {
                    item.assumption_id: item.related_missing_requirement_ids
                    for item in result.assumptions
                },
            )
            connection.execute(
                """
                INSERT INTO framework_assumption_runs (
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

    def get_result(
        self,
        document_id: UUID,
    ) -> FrameworkAssumptionLedgerResult | None:
        with self._connect() as connection:
            run = connection.execute(
                "SELECT * FROM framework_assumption_runs WHERE document_id = ?",
                (str(document_id),),
            ).fetchone()
        if run is None:
            return None
        return FrameworkAssumptionLedgerResult(
            document_id=document_id,
            facts=self.list_facts(document_id),
            assumptions=self.list_assumptions(document_id),
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
    ) -> FrameworkAssumptionLedgerResult | None:
        result = self.get_result(document_id)
        if (
            result is None
            or result.source_fingerprint != source_fingerprint
            or result.model != model
            or result.agent_version != agent_version
        ):
            return None
        return result

    def list_facts(self, document_id: UUID) -> list[LedgerFact]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM framework_ledger_facts
                WHERE document_id = ? ORDER BY fact_id
                """,
                (str(document_id),),
            ).fetchall()
        return [
            LedgerFact(
                fact_id=row["fact_id"],
                title=row["title"],
                description=row["description"],
                evidence_text=row["evidence_text"],
                source_chunk_ids=json.loads(row["source_chunk_ids_json"]),
                source_sections=json.loads(row["source_sections_json"]),
                related_requirement_ids=json.loads(
                    row["related_requirement_ids_json"]
                ),
            )
            for row in rows
        ]

    def list_assumptions(self, document_id: UUID) -> list[LedgerAssumption]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM framework_ledger_assumptions
                WHERE document_id = ? ORDER BY assumption_id
                """,
                (str(document_id),),
            ).fetchall()
            links = {
                name: self._read_links(connection, document_id, name)
                for name in self._LINK_TABLES
            }
        return [
            LedgerAssumption(
                assumption_id=row["assumption_id"],
                title=row["title"],
                description=row["description"],
                assumption_type=row["assumption_type"],
                confidence=row["confidence"],
                reason=row["reason"],
                evidence_text=row["evidence_text"],
                source_chunk_ids=json.loads(row["source_chunk_ids_json"]),
                source_sections=json.loads(row["source_sections_json"]),
                related_requirement_ids=links["requirement"].get(
                    row["assumption_id"], []
                ),
                related_ambiguity_ids=links["ambiguity"].get(
                    row["assumption_id"], []
                ),
                related_conflict_ids=links["conflict"].get(
                    row["assumption_id"], []
                ),
                related_missing_requirement_ids=links[
                    "missing_requirement"
                ].get(row["assumption_id"], []),
                impact_area=row["impact_area"],
                risk_level=row["risk_level"],
                needs_stakeholder_confirmation=bool(
                    row["needs_stakeholder_confirmation"]
                ),
                confirmation_question=row["confirmation_question"],
                status=row["status"],
            )
            for row in rows
        ]

    def get(
        self,
        document_id: UUID,
        assumption_id: str,
    ) -> LedgerAssumption | None:
        return next(
            (
                item
                for item in self.list_assumptions(document_id)
                if item.assumption_id == assumption_id
            ),
            None,
        )

    def update_status(
        self,
        document_id: UUID,
        assumption_id: str,
        status: AssumptionStatus,
    ) -> LedgerAssumption | None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE framework_ledger_assumptions
                SET status = ?
                WHERE document_id = ? AND assumption_id = ?
                """,
                (status.value, str(document_id), assumption_id),
            )
        if cursor.rowcount == 0:
            return None
        return self.get(document_id, assumption_id)

    def _write_links(
        self,
        connection: sqlite3.Connection,
        document_id: str,
        link_name: str,
        values: dict[str, list[str]],
    ) -> None:
        table = self._LINK_TABLES[link_name]
        column = f"{link_name}_id"
        connection.executemany(
            f"""
            INSERT INTO {table} (document_id, assumption_id, {column})
            VALUES (?, ?, ?)
            """,
            [
                (document_id, assumption_id, target_id)
                for assumption_id, target_ids in values.items()
                for target_id in target_ids
            ],
        )

    def _read_links(
        self,
        connection: sqlite3.Connection,
        document_id: UUID,
        link_name: str,
    ) -> dict[str, list[str]]:
        table = self._LINK_TABLES[link_name]
        column = f"{link_name}_id"
        rows = connection.execute(
            f"""
            SELECT assumption_id, {column} FROM {table}
            WHERE document_id = ? ORDER BY {column}
            """,
            (str(document_id),),
        ).fetchall()
        result: dict[str, list[str]] = {}
        for row in rows:
            result.setdefault(row["assumption_id"], []).append(row[column])
        return result

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS framework_assumption_runs (
                    document_id TEXT PRIMARY KEY,
                    source_fingerprint TEXT NOT NULL,
                    model TEXT NOT NULL,
                    agent_version TEXT NOT NULL,
                    execution_time_ms REAL NOT NULL,
                    analyzed_at TEXT NOT NULL,
                    knowledge_graph_updated INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS framework_ledger_facts (
                    document_id TEXT NOT NULL,
                    fact_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    evidence_text TEXT NOT NULL,
                    source_chunk_ids_json TEXT NOT NULL,
                    source_sections_json TEXT NOT NULL,
                    related_requirement_ids_json TEXT NOT NULL,
                    PRIMARY KEY(document_id, fact_id)
                );

                CREATE TABLE IF NOT EXISTS framework_ledger_assumptions (
                    document_id TEXT NOT NULL,
                    assumption_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    assumption_type TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    reason TEXT NOT NULL,
                    evidence_text TEXT NOT NULL,
                    source_chunk_ids_json TEXT NOT NULL,
                    source_sections_json TEXT NOT NULL,
                    impact_area TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    needs_stakeholder_confirmation INTEGER NOT NULL,
                    confirmation_question TEXT NOT NULL,
                    status TEXT NOT NULL,
                    PRIMARY KEY(document_id, assumption_id)
                );

                CREATE TABLE IF NOT EXISTS assumption_requirement_links (
                    document_id TEXT NOT NULL,
                    assumption_id TEXT NOT NULL,
                    requirement_id TEXT NOT NULL,
                    PRIMARY KEY(document_id, assumption_id, requirement_id)
                );
                CREATE TABLE IF NOT EXISTS assumption_ambiguity_links (
                    document_id TEXT NOT NULL,
                    assumption_id TEXT NOT NULL,
                    ambiguity_id TEXT NOT NULL,
                    PRIMARY KEY(document_id, assumption_id, ambiguity_id)
                );
                CREATE TABLE IF NOT EXISTS assumption_conflict_links (
                    document_id TEXT NOT NULL,
                    assumption_id TEXT NOT NULL,
                    conflict_id TEXT NOT NULL,
                    PRIMARY KEY(document_id, assumption_id, conflict_id)
                );
                CREATE TABLE IF NOT EXISTS assumption_missing_requirement_links (
                    document_id TEXT NOT NULL,
                    assumption_id TEXT NOT NULL,
                    missing_requirement_id TEXT NOT NULL,
                    PRIMARY KEY(
                        document_id, assumption_id, missing_requirement_id
                    )
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection
