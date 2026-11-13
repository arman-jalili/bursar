"""SC-9 — the amount submitted equals the amount signed.

Canonical: docs/contracts/settlement-contract-freeze.md §1 (SC-9)
Reference: .pi/architecture/modules/settlement.md#aggregate-settlementorder

Defends module AC #9: the submitted amount equals the signed intent amount, and a mismatch is refused by
`AmountIntegrityViolation` rather than asserted in a comment. The rule has one natural call site:
`mark_submitted` receives both the order's frozen amount and the amount being signed, so "impossible by
construction" is also *checked* at the moment construction could be bypassed.
"""

from __future__ import annotations

import pytest
from src.settlement.domain.errors import AmountIntegrityViolation
from src.settlement.domain.settlement_order import SettlementOrder
from src.shared.domain.money import Money


class TestAmountIntegrity:
    def test_a_different_amount_is_refused_before_submission(self, order) -> None:
        """SC-9 / AC-9: signing 1 micro-USDC for a 42.50 bill must be impossible, not unlikely."""
        with pytest.raises(AmountIntegrityViolation):
            order.mark_submitted("0x" + "aa" * 32, Money(1))

    def test_the_signed_amount_is_accepted(self, order, signed_amount) -> None:
        """SC-9 / AC-9: the honest case passes — the guard must not refuse the signed amount."""
        order.mark_submitted("0x" + "aa" * 32, signed_amount)

    def test_params_use_the_frozen_amount_not_an_argument(self, order) -> None:
        """SC-9 / AC-9: the command amount comes from the order, so no caller can edit it."""
        params = order.command_params()

        assert params["amount_usdc"] == order.amount.micro_usdc

    def test_a_mismatched_amount_cannot_enter_through_the_command_type(
        self, order, intent, network, determination
    ) -> None:
        """SC-9 / AC-9: there is no `amount` argument on the factory, so the signed one is the only one."""
        with pytest.raises(TypeError):
            SettlementOrder.order(  # type: ignore[call-arg]
                intent, network, determination, amount=Money(1)
            )
