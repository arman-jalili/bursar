"""A-10 / A-11 — a reservation resolves exactly once, and committed spend never shrinks (AC 5).

Canonical: docs/contracts/authority-contract-freeze.md §1
Reference: .pi/architecture/modules/authority.md#aggregate-cap-ledge

Two failures this defends against: a reservation that resolves twice (money counted twice, or lost), and a
ledger whose committed total can be un-committed (the same cap spent again). Both are asserted by requiring
the second attempt to raise.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from src.authority.domain.cap_ledger import CapLedger
from src.authority.domain.errors import ReservationAlreadyResolved
from tests.unit.authority._builders import NOW, an_intent_id, usdc


def a_ledger(*, committed: str = "0") -> CapLedger:
    return CapLedger(
        day="2026-11-14",
        cap=usdc("150"),
        committed=usdc(committed),
        reserved=usdc("0"),
    )


class TestReservationResolvesOnce:
    def test_committing_a_hold_moves_it_from_reserved_to_committed(self) -> None:
        """A-10: commit is the only way spend becomes permanent."""
        ledger = a_ledger()
        reservation = ledger.try_reserve(an_intent_id(), usdc("25"), NOW + timedelta(minutes=15))

        ledger.commit(reservation)

        assert ledger.committed == usdc("25")
        assert ledger.reserved == usdc("0")

    def test_committing_twice_raises(self) -> None:
        """A-10: a second commit is a duplicate settlement — it must fail loudly (AC 5)."""
        ledger = a_ledger()
        reservation = ledger.try_reserve(an_intent_id(), usdc("25"), NOW + timedelta(minutes=15))
        ledger.commit(reservation)

        with pytest.raises(ReservationAlreadyResolved):
            ledger.commit(reservation)

    def test_commit_then_release_raises(self) -> None:
        """A-10: committed and released are mutually exclusive, so a settled payment cannot be refunded
        into headroom."""
        ledger = a_ledger()
        reservation = ledger.try_reserve(an_intent_id(), usdc("25"), NOW + timedelta(minutes=15))
        ledger.commit(reservation)

        with pytest.raises(ReservationAlreadyResolved):
            ledger.release(reservation)

    def test_releasing_twice_raises(self) -> None:
        """A-10: releasing twice would invent headroom that the chain never returned."""
        ledger = a_ledger()
        reservation = ledger.try_reserve(an_intent_id(), usdc("25"), NOW + timedelta(minutes=15))
        ledger.release(reservation)

        with pytest.raises(ReservationAlreadyResolved):
            ledger.release(reservation)

    def test_a_rejected_second_call_does_not_change_the_totals(self) -> None:
        """A-10/AC 5: `committed + reserved` is unchanged by the call that was refused."""
        ledger = a_ledger()
        reservation = ledger.try_reserve(an_intent_id(), usdc("25"), NOW + timedelta(minutes=15))
        ledger.commit(reservation)
        before = ledger.committed + ledger.reserved

        with pytest.raises(ReservationAlreadyResolved):
            ledger.commit(reservation)

        assert ledger.committed + ledger.reserved == before

    def test_release_returns_headroom(self) -> None:
        """A-10: a payment that provably did not happen must free the cap for a legitimate retry."""
        ledger = a_ledger()
        reservation = ledger.try_reserve(an_intent_id(), usdc("25"), NOW + timedelta(minutes=15))

        ledger.release(reservation)

        assert ledger.headroom == usdc("150")
