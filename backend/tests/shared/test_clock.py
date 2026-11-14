"""Clock — time is injected because approvals expire and caps are per-day.

Canonical: docs/architecture/modules/authority.md#components
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from src.shared.domain.clock import Clock, FrozenClock, SystemClock


def test_system_clock_is_utc_aware() -> None:
    assert SystemClock().now().tzinfo is not None


def test_frozen_clock_advances_deterministically() -> None:
    clock = FrozenClock(datetime(2026, 11, 14, 9, 0, tzinfo=UTC))
    assert clock.now().hour == 9
    assert clock.advance(timedelta(hours=2)).hour == 11
    assert clock.now().hour == 11


def test_frozen_clock_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FrozenClock(datetime(2026, 11, 14, 9, 0))


def test_both_satisfy_the_protocol() -> None:
    assert isinstance(SystemClock(), Clock)
    assert isinstance(FrozenClock(), Clock)


def test_approval_expiry_scenario_is_deterministic() -> None:
    clock = FrozenClock(datetime(2026, 11, 14, 9, 0, tzinfo=UTC))
    expires_at = clock.now() + timedelta(minutes=15)
    clock.advance(timedelta(minutes=16))
    assert clock.now() > expires_at  # ApprovalExpired becomes assertable, not flaky
