"""Clock — time as an injected dependency.

Canonical: .pi/architecture/modules/authority.md#components
Reference: .pi/architecture/decisions/ADR-003-cross-context-communication.md

Time is domain data here, not an implementation detail: an approval expires, a cap is per-day, a
reservation has a TTL, and evidence records when a determination was read. So `now()` is injected
and a test can pin it — otherwise "approval expired" tests are flaky by construction.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

__all__ = ["Clock", "FrozenClock", "SystemClock"]


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime:
        """Timezone-aware UTC now."""


class SystemClock:
    """Production clock. Always UTC-aware."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock:
    """Test clock you can move by hand.

    >>> clock = FrozenClock(datetime(2026, 11, 14, 9, 0, tzinfo=UTC))
    >>> clock.now().hour
    9
    >>> clock.advance(timedelta(hours=2)).hour
    11
    """

    def __init__(self, at: datetime | None = None) -> None:
        if at is not None and at.tzinfo is None:
            raise ValueError("FrozenClock needs a timezone-aware datetime.")
        self._now = at or datetime(2026, 11, 14, 9, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> datetime:
        self._now = self._now + delta
        return self._now
