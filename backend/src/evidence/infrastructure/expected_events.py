"""Publisher-outbox read model for the witness-only check (E-10).

Canonical: .pi/architecture/modules/evidence.md#ports
Reference: docs/contracts/evidence-contract-freeze.md §2.6

Evidence is a witness, not a guard: it never makes a publisher wait for a seal. The price of that
independence is that a gap must be *findable afterwards*. This adapter answers the read-side
question — which facts were published in a window? — by reading the publishers' transactional
outboxes (ADR-003). It tolerates an outbox that does not exist yet (a context still in Phase A), which
keeps the report usable while the system is being built.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.evidence.domain.ids import EventId
from src.evidence.domain.ports import ExpectedEvent, ExpectedEventsPort

__all__ = ["SqlExpectedEvents"]

#: Outboxes of the publishers Evidence consumes. A missing table is skipped, not an error.
PUBLISHER_OUTBOXES: tuple[str, ...] = (
    "authority_outbox",
    "billing_outbox",
    "settlement_outbox",
    "mandate_outbox",
)


class SqlExpectedEvents(ExpectedEventsPort):
    """Read the publisher facts that should have a witness in the window."""

    def __init__(self, session: AsyncSession, *, outboxes: Sequence[str] = PUBLISHER_OUTBOXES):
        self._session = session
        self._outboxes = tuple(outboxes)

    async def expected(self, *, since: datetime, until: datetime) -> Sequence[ExpectedEvent]:
        names = await self._existing_outboxes()
        events: list[ExpectedEvent] = []
        for name in names:
            statement = text(
                f"SELECT event_id, event_name, occurred_at FROM {name} "
                "WHERE occurred_at >= :since AND occurred_at < :until "
                "ORDER BY occurred_at, event_id"
            )
            rows = await self._session.execute(statement, {"since": since, "until": until})
            for row in rows:
                events.append(
                    ExpectedEvent(
                        event_id=EventId(str(row[0])),
                        event_type=str(row[1]),
                        occurred_at=_aware(row[2]),
                    )
                )
        events.sort(key=lambda event: (event.occurred_at, str(event.event_id)))
        return tuple(events)

    async def _existing_outboxes(self) -> list[str]:
        rows = await self._session.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'table'")
        )
        present = {str(row[0]) for row in rows}
        return [name for name in self._outboxes if name in present]


def _aware(value: object) -> datetime:
    """SQLite stores timestamps without an offset; the report compares them, so normalise to UTC."""
    from datetime import UTC

    moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment
