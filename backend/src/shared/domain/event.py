"""DomainEvent — an immutable fact, in the past tense, with delivery metadata.

Canonical: .pi/architecture/decisions/ADR-003-cross-context-communication.md
Reference: .pi/architecture/modules/authority.md#domain-events

Rules encoded here, not just documented:

* **Past tense, immutable.** A subscriber may not reject a fact. If it cannot process an event
  it retries and then quarantines — it never rolls back the publisher.
* **At-least-once delivery.** Every event carries `event_id` so subscribers can dedupe on
  `(event_id, handler)`; that is why the field is mandatory rather than convenient.
* **Correlation.** `correlation_id` carries the payment intent id across five contexts, which is
  what lets an auditor assemble the story of one payment from five event streams.
* **Refusals are events.** `PaymentRefused` is a `DomainEvent` like any other; there is no
  "lesser" event type for failures.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from typing import Any, ClassVar

__all__ = ["DomainEvent", "new_event_id", "utcnow"]


def new_event_id() -> str:
    """Event identity for at-least-once dedupe (ADR-003)."""
    return uuid.uuid4().hex


def utcnow() -> datetime:
    """Timezone-aware UTC. Naive datetimes are a bug in an audit trail."""
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class DomainEvent:
    """Base class for every domain event.

    Subclasses add payload fields and declare `event_name`:

        @dataclass(frozen=True, slots=True, kw_only=True)
        class PayeeQuarantined(DomainEvent):
            event_name: ClassVar[str] = "PayeeQuarantined"
            payee_id: str
            reason: str
    """

    #: Wire name. Stable: it appears in evidence envelopes and in the event-flow diagrams.
    event_name: ClassVar[str] = "DomainEvent"

    event_id: str = field(default_factory=new_event_id)
    occurred_at: datetime = field(default_factory=utcnow)
    #: The aggregate that produced the fact.
    aggregate_id: str = ""
    #: Ties events of one payment together across contexts.
    correlation_id: str | None = None
    #: Envelope schema version — evidence must stay verifiable as payloads evolve.
    schema_version: int = 1

    def to_payload(self) -> dict[str, Any]:
        """Payload for the evidence envelope (everything except delivery metadata).

        `event_id`/`occurred_at`/`correlation_id` are carried by the envelope itself, so they
        stay out of the fact payload — otherwise a replay with a new event id would change the
        sealed bytes of an identical fact.
        """
        meta = {"event_id", "occurred_at", "aggregate_id", "correlation_id", "schema_version"}
        # `fields()` rather than `vars()`: events are slotted dataclasses and have no `__dict__`.
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name not in meta}

    @property
    def name(self) -> str:
        return self.event_name
