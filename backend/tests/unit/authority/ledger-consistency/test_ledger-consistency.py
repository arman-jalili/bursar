"""A-11 / A-12 — committed never shrinks within a day, and the day key is fixed (AC 13).

Canonical: docs/contracts/authority-contract-freeze.md §1
Reference: docs/architecture/modules/authority.md#aggregate-cap-ledge

The asymmetry that makes the ledger auditable: `committed` is monotonic per day, only `reserved` moves back
down. A ledger that could un-commit settled spend would let one cap be spent twice — the same failure the
chain's nullifier prevents, one layer up.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from src.authority.domain.cap_ledger import CapLedger, Reservation, ReservationStatus
from src.authority.domain.errors import ReservationAlreadyResolved
from tests.unit.authority._builders import NOW, an_intent_id, usdc


class TestLedgerConsistency:
    def test_committed_grows_by_exactly_the_reserved_amount(self) -> None:
        """A-11: commit moves the amount across, so committed equals the sum of settlements."""
        ledger = CapLedger(
            day="2026-11-14", cap=usdc("150"), committed=usdc("0"), reserved=usdc("0")
        )
        reservation = ledger.try_reserve(an_intent_id(), usdc("42.50"), NOW + timedelta(minutes=15))

        ledger.commit(reservation)

        assert ledger.committed == usdc("42.50")
        assert ledger.reserved == usdc("0")

    def test_release_never_touches_committed(self) -> None:
        """A-11: releasing a hold returns reserved only — settled spend is not refundable."""
        ledger = CapLedger(
            day="2026-11-14", cap=usdc("150"), committed=usdc("50"), reserved=usdc("0")
        )
        reservation = ledger.try_reserve(an_intent_id(), usdc("25"), NOW + timedelta(minutes=15))

        ledger.release(reservation)

        assert ledger.committed == usdc("50")
        assert ledger.reserved == usdc("0")

    def test_a_reservation_keeps_the_day_it_was_held_on(self) -> None:
        """A-12: the day key is fixed per reservation, so a late settlement cannot land in tomorrow."""
        reservation = Reservation.hold(
            intent_id=an_intent_id(),
            amount=usdc("25"),
            day="2026-11-14",
            expires_at=NOW + timedelta(minutes=15),
        )

        assert reservation.day == "2026-11-14"
        assert reservation.status is ReservationStatus.HELD

    def test_a_resolved_reservation_cannot_move_again(self) -> None:
        """A-10/A-11: resolved is final, which is what keeps the totals reconcilable with the chain."""
        ledger = CapLedger(
            day="2026-11-14", cap=usdc("150"), committed=usdc("0"), reserved=usdc("0")
        )
        reservation = ledger.try_reserve(an_intent_id(), usdc("25"), NOW + timedelta(minutes=15))
        ledger.commit(reservation)

        with pytest.raises(ReservationAlreadyResolved):
            ledger.release(reservation)
