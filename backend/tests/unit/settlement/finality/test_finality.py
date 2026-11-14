"""SC-7 — finality is a confirmation count, not a flag.

Canonical: docs/contracts/settlement-contract-freeze.md §1 (SC-7)
Reference: docs/architecture/modules/settlement.md#aggregate-settlementorder

Defends module AC #7: zero confirmations means `PENDING` and **no cap commit**; the network's required
count means `CONFIRMED` and the commit. The threshold is a field of `ChainNetwork` (SC-11), so an Anvil
run (1 confirmation) and a Sepolia run (2) can differ without changing the receipt type.
"""

from __future__ import annotations

import pytest
from src.settlement.domain.services import FinalityPolicy
from src.settlement.domain.values import SettlementStatus

from tests.unit.settlement._fixtures import a_receipt, an_anvil_network


class TestFinality:
    def test_zero_confirmations_are_not_final(self) -> None:
        """SC-7 / AC-7: a mined transaction at depth 0 can still be reorged — no commit yet."""
        receipt = a_receipt(confirmations=0)

        assert (
            FinalityPolicy().is_final(receipt, an_anvil_network(confirmations_required=1)) is False
        )

    def test_the_required_confirmation_count_is_final(self) -> None:
        """SC-7 / AC-7: at the threshold the settlement is final and the cap may commit."""
        receipt = a_receipt(confirmations=2)

        assert (
            FinalityPolicy().is_final(receipt, an_anvil_network(confirmations_required=2)) is True
        )

    def test_below_the_threshold_maps_to_pending(self) -> None:
        """SC-7 / AC-7: `PENDING` is a non-committing state, so a reorg cannot leave a committed cap."""
        receipt = a_receipt(confirmations=1)

        status = FinalityPolicy().status_for(receipt, an_anvil_network(confirmations_required=2))

        assert status is SettlementStatus.PENDING

    def test_at_the_threshold_maps_to_confirmed(self) -> None:
        """SC-7 / AC-7: only `CONFIRMED` commits the reservation."""
        receipt = a_receipt(confirmations=2)

        status = FinalityPolicy().status_for(receipt, an_anvil_network(confirmations_required=2))

        assert status is SettlementStatus.CONFIRMED

    def test_concluding_before_finality_is_refused(self, order, signed_amount) -> None:
        """SC-7 / AC-7: `conclude` must refuse a shallow receipt instead of committing early."""
        order.mark_submitted("0x" + "aa" * 32, signed_amount)

        from src.settlement.domain.errors import SettlementNotFinal

        with pytest.raises(SettlementNotFinal):
            order.conclude(a_receipt(confirmations=0, order_id=order.id))
