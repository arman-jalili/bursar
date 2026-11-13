"""SC-6 — a replayed nullifier reverts on-chain, and the app records a refusal.

Canonical: docs/contracts/settlement-contract-freeze.md §1 (SC-6)
Reference: .pi/architecture/modules/settlement.md#components-nullifier

Defends module AC #6 (scenario 6, bypass path): even with the app bypassed, the contract reverts on a
spent nullifier, and Settlement records `SettlementReverted` — not a retry. The Anvil integration run is
Phase-B evidence; the rules asserted here are the ones that make the app's half checkable: an on-chain
spent marker is refused locally first, and a reverted order is terminal.
"""

from __future__ import annotations

import pytest
from src.settlement.domain.errors import DuplicateSettlementBlocked, IllegalTransition
from src.settlement.domain.services import NullifierPolicy
from src.settlement.domain.values import Nullifier, ReceiptStatus, SettlementStatus

from tests.unit.settlement._fixtures import a_receipt


class _OnChainSpendView:
    """Minimal stand-in for `ChainGateway.is_nullifier_spent` — the read, not the adapter."""

    def __init__(self, spent: bool) -> None:
        self._spent = spent

    async def is_nullifier_spent(self, nullifier: Nullifier) -> bool:
        return self._spent


class TestNullifierOnChain:
    async def test_an_on_chain_spent_marker_is_refused_before_submission(self) -> None:
        """SC-6 / AC-6: the app refuses one layer earlier than the contract, with the same verdict."""
        marker = Nullifier.derive("ab" * 32, "hh-1")
        gateway = _OnChainSpendView(spent=True)

        with pytest.raises(DuplicateSettlementBlocked):
            NullifierPolicy().guard_unspent(
                marker, already_spent=await gateway.is_nullifier_spent(marker)
            )

    def test_a_reverted_order_is_terminal(self, order, signed_amount) -> None:
        """SC-6 / AC-6: a revert concludes the order; no path back to the chain exists."""
        order.mark_submitted("0x" + "aa" * 32, signed_amount)
        order.conclude(
            a_receipt(order_id=order.id, status=ReceiptStatus.REVERTED, revert_reason="NullifierSpent")
        )

        with pytest.raises(IllegalTransition):
            order.mark_submitted("0x" + "bb" * 32, signed_amount)

    def test_a_revert_is_recorded_with_its_reason(self, order, signed_amount) -> None:
        """SC-6 / AC-6: the contract's reason is evidence — the console and the envelope both need it."""
        order.mark_submitted("0x" + "aa" * 32, signed_amount)

        order.conclude(
            a_receipt(order_id=order.id, status=ReceiptStatus.REVERTED, revert_reason="NullifierSpent")
        )

        reverted = [event for event in order.pull_events() if event.name == "SettlementReverted"]

        assert reverted and reverted[0].revert_reason == "NullifierSpent"
        assert order.status is SettlementStatus.REVERTED
