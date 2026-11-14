"""A-8 — a refusal produces no reservation and no dispatch (AC 12).

Canonical: docs/contracts/authority-contract-freeze.md §1
Reference: docs/architecture/modules/authority.md#aggregate-determination

The half of the refusal contract that is easy to lose: saying "no" is not enough, the ledger must be
untouched and no settlement order may exist. Asserted by checking the ledger totals across a refused hold.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from src.authority.domain.cap_ledger import CapLedger
from src.authority.domain.determination import Determination
from src.authority.domain.errors import CapExceeded, DispatchWithoutAuthority
from src.authority.domain.values import DenialReason
from src.mandate.domain.values import PayeeStatus
from tests.unit.authority._builders import NOW, an_intent_id, usdc


class TestRefusalHasNoSideEffect:
    def test_a_refused_reservation_leaves_committed_and_reserved_unchanged(self) -> None:
        """A-8/AC 12: after CapExceeded the ledger is byte-identical to before."""
        ledger = CapLedger(
            day="2026-11-14", cap=usdc("150"), committed=usdc("85"), reserved=usdc("40")
        )

        with pytest.raises(CapExceeded):
            ledger.try_reserve(an_intent_id(), usdc("50"), NOW + timedelta(minutes=15))

        assert ledger.committed == usdc("85")
        assert ledger.reserved == usdc("40")

    def test_a_denial_cannot_be_passed_to_the_dispatch_gate(self) -> None:
        """A-8: the guard raises, so a DENY cannot become a settlement order downstream."""
        determination = Determination.deny(
            intent_id=an_intent_id(),
            reasons=[DenialReason.CAP_EXCEEDED],
            constitution_version=3,
            payee_status_read=PayeeStatus.ELIGIBLE,
            read_at=NOW,
            ledger_snapshot=usdc("150"),
        )

        with pytest.raises(DispatchWithoutAuthority):
            determination.assert_not_a_refusal()

    def test_a_refusal_does_not_consume_headroom_for_later_attempts(self) -> None:
        """A-8: the next legitimate attempt still sees the full headroom."""
        ledger = CapLedger(
            day="2026-11-14", cap=usdc("150"), committed=usdc("0"), reserved=usdc("0")
        )

        with pytest.raises(CapExceeded):
            ledger.try_reserve(an_intent_id(), usdc("200"), NOW + timedelta(minutes=15))

        assert ledger.headroom == usdc("150")
