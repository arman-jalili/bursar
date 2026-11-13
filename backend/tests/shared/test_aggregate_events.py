"""AggregateRoot + DomainEvent — fact recording and delivery metadata (ADR-003).

Canonical: .pi/architecture/decisions/ADR-003-cross-context-communication.md
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

import pytest
from src.shared.domain.aggregate import AggregateRoot
from src.shared.domain.event import DomainEvent


@dataclass(frozen=True, slots=True, kw_only=True)
class PayeeQuarantined(DomainEvent):
    event_name: ClassVar[str] = "PayeeQuarantined"
    payee_id: str = ""
    reason: str = "bank_digest_mismatch"


@dataclass(eq=False)
class Payee(AggregateRoot):
    id: str
    status: str = "eligible"

    def review_digest(self, matches: bool) -> None:
        if matches:
            return
        self.status = "quarantined"
        self.record(PayeeQuarantined(aggregate_id=self.id, payee_id=self.id))


def test_events_are_recorded_and_drained_once() -> None:
    payee = Payee(id="p1")
    payee.review_digest(matches=False)
    assert len(payee.pending_events) == 1

    drained = payee.pull_events()
    assert len(drained) == 1
    assert payee.pull_events() == ()  # second drain is empty: outbox owns delivery


def test_no_event_when_nothing_happened() -> None:
    payee = Payee(id="p1")
    payee.review_digest(matches=True)
    assert payee.pending_events == ()


def test_drained_batch_is_immutable() -> None:
    payee = Payee(id="p1")
    payee.record(PayeeQuarantined(aggregate_id="p1"))
    batch = payee.pull_events()
    assert isinstance(batch, tuple)


def test_event_identity_and_correlation_are_automatic() -> None:
    event = PayeeQuarantined(aggregate_id="p1")
    assert event.event_id
    assert event.occurred_at.tzinfo is not None  # audit trail must never be naive
    assert event.correlation_id is None
    first, second = PayeeQuarantined(aggregate_id="p1"), PayeeQuarantined(aggregate_id="p1")
    assert first.event_id != second.event_id  # at-least-once dedupe key


def test_event_is_immutable() -> None:
    event = PayeeQuarantined(aggregate_id="p1")
    with pytest.raises((AttributeError, TypeError)):
        event.reason = "frozen"  # type: ignore[misc]


def test_payload_excludes_delivery_metadata() -> None:
    """The sealed bytes of a fact must not change when it is redelivered (ADR-003/E-1)."""
    event = PayeeQuarantined(
        aggregate_id="p1",
        payee_id="p1",
        correlation_id="intent-7",
        occurred_at=datetime(2026, 11, 14, 9, 0, tzinfo=UTC),
    )
    payload = event.to_payload()
    assert payload == {"payee_id": "p1", "reason": "bank_digest_mismatch"}
    assert "event_id" not in payload
    assert "correlation_id" not in payload


def test_event_name_is_wire_stable() -> None:
    assert PayeeQuarantined(aggregate_id="p1").name == "PayeeQuarantined"


def test_aggregate_identity_equality_not_state_equality() -> None:
    a, b = Payee(id="p1"), Payee(id="p1")
    assert a is not b and a != b  # two instances are not the same aggregate


def test_aggregate_has_no_setters_surface() -> None:
    assert not hasattr(Payee, "set_status")
