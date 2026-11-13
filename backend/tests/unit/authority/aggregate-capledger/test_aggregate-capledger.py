"""A-9 / A-10 — the ledger aggregate owns the hold lifecycle, not the adapter.

Canonical: docs/contracts/authority-contract-freeze.md §1
Reference: .pi/architecture/modules/authority.md#aggregate-cap-ledge

The aggregate is the consistency boundary: `try_reserve` is the only way a hold comes into existence, and the
ledger — not a caller — decides whether the cap allows it. Asserted through the aggregate API so a future
adapter cannot take the decision away from it.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from src.authority.domain.cap_ledger import CapLedger, ReservationStatus
from src.authority.domain.errors import CapExceeded
from tests.unit.authority._builders import NOW, an_intent_id, usdc


def a_ledger(*, committed: str = "0") -> CapLedger:
    return CapLedger(
        day="2026-11-14", cap=usdc("150"), committed=usdc(committed), reserved=usdc("0")
    )


class TestCapLedgerAggregate:
    def test_a_hold_is_created_only_through_the_ledger(self) -> None:
        """A-9: the aggregate hands out the reservation, so it cannot be conjured around the cap."""
        ledger = a_ledger()

        reservation = ledger.try_reserve(an_intent_id(), usdc("25"), NOW + timedelta(minutes=15))

        assert reservation.status is ReservationStatus.HELD
        assert reservation.amount == usdc("25")

    def test_the_ledger_counts_the_hold_against_its_own_headroom(self) -> None:
        """A-9: reserved is the ledger's own total, so two holds compose."""
        ledger = a_ledger()

        ledger.try_reserve(an_intent_id(), usdc("100"), NOW + timedelta(minutes=15))
        ledger.try_reserve(an_intent_id(), usdc("40"), NOW + timedelta(minutes=15))

        assert ledger.reserved == usdc("140")
        assert ledger.headroom == usdc("10")

    def test_a_hold_that_would_overdraw_is_refused_by_the_aggregate(self) -> None:
        """A-9: 140 + 25 against a 150 cap must raise, not silently clamp."""
        ledger = a_ledger()
        ledger.try_reserve(an_intent_id(), usdc("140"), NOW + timedelta(minutes=15))

        with pytest.raises(CapExceeded):
            ledger.try_reserve(an_intent_id(), usdc("25"), NOW + timedelta(minutes=15))

    def test_the_ledger_day_is_part_of_its_identity(self) -> None:
        """A-12: a rollover is a different ledger row, so the day travels with the aggregate."""
        assert a_ledger().day == "2026-11-14"
