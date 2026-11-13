"""SC-5 / SC-7 — the two domain services and the rules they own.

Canonical: docs/contracts/settlement-contract-freeze.md §1 (SC-5, SC-7)
Reference: .pi/architecture/modules/settlement.md#domain-services

Defends module AC #5 and AC #7 at the service boundary. Neither rule belongs on an aggregate: the order
already carries its nullifier, and a receipt must not know a network's confirmation policy. Asserted as
behaviour, not existence — a derivation that disagrees with the aggregate and a finality policy that
ignores the network are both bugs this suite must catch.
"""

from __future__ import annotations

import pytest
from src.settlement.domain.errors import DuplicateSettlementBlocked
from src.settlement.domain.services import FinalityPolicy, NullifierPolicy
from src.settlement.domain.values import ReceiptStatus, SettlementStatus

from tests.unit.settlement._fixtures import a_receipt, an_anvil_network


class TestNullifierPolicy:
    def test_derivation_is_repeatable(self) -> None:
        """SC-5: derive twice, get the same marker — otherwise a retry looks like a new invoice."""
        policy = NullifierPolicy()

        assert policy.derive("ab" * 32, "hh-1").same_as(policy.derive("ab" * 32, "hh-1"))

    def test_a_spent_marker_is_a_duplicate_settlement(self) -> None:
        """SC-5: the service owns the local refusal, so every caller refuses identically."""
        policy = NullifierPolicy()
        marker = policy.derive("ab" * 32, "hh-1")

        with pytest.raises(DuplicateSettlementBlocked):
            policy.guard_unspent(marker, already_spent=True)


class TestFinalityPolicy:
    def test_an_anchor_receipt_is_not_a_payment(self) -> None:
        """SC-7: an anchor is a receipt, but it never concludes a settlement order."""
        policy = FinalityPolicy()

        assert policy.status_for(a_receipt(is_anchor=True), an_anvil_network()) is not (
            SettlementStatus.CONFIRMED
        )

    def test_a_reverted_receipt_maps_to_reverted(self) -> None:
        """SC-7 / SC-6: a chain refusal is a refusal status, never PENDING-forever."""
        receipt = a_receipt(confirmations=3, status=ReceiptStatus.REVERTED, revert_reason="NullifierSpent")

        assert (
            FinalityPolicy().status_for(receipt, an_anvil_network(confirmations_required=1))
            is SettlementStatus.REVERTED
        )

    def test_a_shallow_receipt_is_not_final_for_a_two_confirmation_network(self) -> None:
        """SC-7: the policy reads the network, so one receipt can be final on Anvil and not on Sepolia."""
        receipt = a_receipt(confirmations=1)
        policy = FinalityPolicy()

        assert policy.is_final(receipt, an_anvil_network(confirmations_required=1)) is True
        assert policy.is_final(receipt, an_anvil_network(confirmations_required=2)) is False
