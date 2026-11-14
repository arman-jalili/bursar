"""E-10 — the ports let Evidence detect a missing witness after the fact.

Canonical: docs/contracts/evidence-contract-freeze.md §1
Reference: docs/architecture/modules/evidence.md#ports

Evidence is a witness, not a guard: when it is down the payment still moves, and the gap must be
findable afterwards by comparing the publisher's expected facts with the processed-event ledger. That
comparison is the `WitnessReport` read model. Fails today from `WitnessReport.missing`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.evidence.application.services import WitnessReport
from src.evidence.domain.ids import EventId
from src.evidence.domain.ports import ExpectedEvent

from tests.unit.evidence._fixtures import FakeExpectedEvents, FakeProcessedEvents


class TestPorts:
    async def test_a_published_fact_with_no_envelope_is_reported_as_missing(self) -> None:
        """E-10: the unsealed event id is reported; the sealed one is not."""
        since = datetime(2026, 11, 13, 11, 0, tzinfo=UTC)
        until = datetime(2026, 11, 13, 13, 0, tzinfo=UTC)
        expected = FakeExpectedEvents(
            [
                ExpectedEvent(
                    event_id=EventId("evt-sealed"),
                    event_type="PaymentAllowed",
                    occurred_at=since,
                ),
                ExpectedEvent(
                    event_id=EventId("evt-missing"),
                    event_type="PaymentRefused",
                    occurred_at=since,
                ),
            ]
        )
        processed = FakeProcessedEvents()
        await processed.claim(EventId("evt-sealed"), "seal")

        report = WitnessReport(expected=expected, processed=processed)
        missing = await report.missing(since=since, until=until)

        assert missing == ("evt-missing",)
