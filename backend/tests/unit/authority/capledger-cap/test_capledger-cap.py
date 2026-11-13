"""A-9 — committed + reserved never exceeds the cap; the check and the hold are one step (AC 4).

Canonical: docs/contracts/authority-contract-freeze.md §1
Reference: .pi/architecture/modules/authority.md#aggregate-cap-ledge

Scenario 4: six 25 USDC invoices against a 150 USDC cap. The sixth must be refused, and it must be refused
*without reserving anything* — a partial reservation is how a split attempt half-succeeds. The
concurrency proof (six racers) is an integration test in Phase B; what is frozen here is the rule the
atomic update must express.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from src.authority.domain.cap_ledger import CapLedger
from src.authority.domain.errors import CapExceeded
from tests.unit.authority._builders import NOW, an_intent_id, usdc


def a_ledger(*, cap: str = "150", committed: str = "0", reserved: str = "0") -> CapLedger:
    return CapLedger(
        day="2026-11-14",
        cap=usdc(cap),
        committed=usdc(committed),
        reserved=usdc(reserved),
    )


class TestCapLedgerCap:
    def test_a_reservation_within_headroom_succeeds(self) -> None:
        """A-9: the honest case must work — 25 USDC against 150 with nothing committed."""
        ledger = a_ledger()

        reservation = ledger.try_reserve(an_intent_id(), usdc("25"), NOW + timedelta(minutes=15))

        assert reservation.amount == usdc("25")

    def test_a_reservation_beyond_headroom_is_refused(self) -> None:
        """A-9: 25 USDC with 150 already committed must raise CapExceeded, not over-book."""
        ledger = a_ledger(committed="150")

        with pytest.raises(CapExceeded):
            ledger.try_reserve(an_intent_id(), usdc("25"), NOW + timedelta(minutes=15))

    def test_a_refused_reservation_leaves_the_ledger_untouched(self) -> None:
        """A-9/A-8: refusal has no side effect — `reserved` is unchanged after CapExceeded."""
        ledger = a_ledger(committed="140")

        with pytest.raises(CapExceeded):
            ledger.try_reserve(an_intent_id(), usdc("25"), NOW + timedelta(minutes=15))

        assert ledger.reserved == usdc("0")
        assert ledger.headroom == usdc("10")

    def test_headroom_counts_committed_and_reserved_together(self) -> None:
        """A-9: headroom is cap minus both, so a hold shrinks the room a second hold can claim."""
        ledger = a_ledger(committed="85", reserved="40")

        assert ledger.headroom == usdc("25")

    def test_the_sixth_split_invoice_is_refused(self) -> None:
        """A-9, scenario 4: five holds of 25 fit a 150 cap; the sixth does not."""
        ledger = a_ledger(cap="150")

        for _ in range(6):
            ledger.try_reserve(an_intent_id(), usdc("25"), NOW + timedelta(minutes=15))

        assert ledger.reserved == usdc("150")
