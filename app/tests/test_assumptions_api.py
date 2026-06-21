from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.routes import assumptions as assumptions_route
from app.main import app
from app.models.assumptions import AssumptionLedgerResult
from app.tests.test_assumption_ledger import build_ledger

client = TestClient(app)


class StubAssumptionService:
    def __init__(self) -> None:
        self.force_refresh = False

    def get_ledger(
        self,
        document_id: UUID,
        *,
        force_refresh: bool = False,
    ) -> AssumptionLedgerResult:
        self.force_refresh = force_refresh
        ledger = build_ledger(document_id)
        return AssumptionLedgerResult(
            document_id=document_id,
            facts=ledger.facts,
            assumptions=ledger.assumptions,
            total_facts=1,
            total_assumptions=1,
            pending_confirmation=1,
            cached=False,
            model="test-model",
            prompt_version="assumption-ledger-v1",
            analyzed_at=datetime.now(UTC),
        )


def test_get_assumption_ledger_separates_facts_and_assumptions(monkeypatch) -> None:
    document_id = uuid4()
    service = StubAssumptionService()
    monkeypatch.setattr(
        assumptions_route,
        "get_assumption_service",
        lambda: service,
    )

    response = client.get(
        f"/assumptions/{document_id}?force_refresh=true"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["facts"][0]["fact_id"] == "FACT-001"
    assumption = body["assumptions"][0]
    assert assumption["assumption_id"] == "ASM-001"
    assert assumption["confidence"] == 0.72
    assert assumption["needs_confirmation"] is True
    assert assumption["affected_outputs"] == ["requirements.FR-001.priority"]
    assert body["pending_confirmation"] == 1
    assert service.force_refresh is True
