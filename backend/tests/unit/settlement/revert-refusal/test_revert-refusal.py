"""SC-6 / SC-8 — a revert is a refusal: terminal, one event, never a retry.

Canonical: docs/contracts/settlement-contract-freeze.md §1 (SC-6, SC-8)
Reference: .pi/architecture/modules/settlement.md#aggregate-settlementorder

Defends module AC #8: a reverted order never retries, and exactly one outbox `SettlementReverted` exists
per order. This is the timeout double-pay defence: the tempting "it failed, try again" branch is exactly
the branch that pays twice, so it must not exist. A refused dispatch also leaves no transaction behind.
"""

from __future__ import annotations

import pytest
from src.authority.domain.values import DeterminationVerdict
from src.settlement.domain.errors import DispatchWithoutAuthority
from src.settlement.domain.settlement_order import SettlementOrder
from src.settlement.domain.values import ReceiptStatus, SettlementStatus

from tests.unit.settlement._fixtures import a_determination, a_receipt


class TestRevertIsRefusal:
    def test_a_reverted_order_never_retries(self, order, signed_amount) -> None:
        """SC-8 / AC-8: there is no legal second submission after a revert (SC-6)."""
        order.mark_submitted("0x" + "aa" * 32, signed_amount)
        order.conclude(
            a_receipt(order_id=order.id, status=ReceiptStatus.REVERTED, revert_reason="NullifierSpent")
        )

        from src.settlement.domain.errors import IllegalTransition

        with pytest.raises(IllegalTransition):
            order.mark_submitted("0x" + "bb" * 32, signed_amount)

    def test_exactly_one_revert_event_is_recorded(self, order, signed_amount) -> None:
        """SC-8 / AC-8: Authority reconciles on this event; two would double-release a reservation."""
        order.mark_submitted("0x" + "aa" * 32, signed_amount)
        order.conclude(
            a_receipt(order_id=order.id, status=ReceiptStatus.REVERTED, revert_reason="NullifierSpent")
        )

        reverted = [event for event in order.pull_events() if event.name == "SettlementReverted"]

        assert len(reverted) == 1
        assert order.status is SettlementStatus.REVERTED

    def test_a_refused_dispatch_produces_no_transaction(self, intent, network) -> None:
        """SC-8 / AC-8: no authority means no order and therefore no tx hash to retry."""
        denial = a_determination(DeterminationVerdict.DENY, intent_id=intent.intent_id)

        with pytest.raises(DispatchWithoutAuthority):
            SettlementOrder.order(intent, network, denial)

    def test_a_revert_does_not_commit_the_cap(self, order, signed_amount) -> None:
        """SC-8 / AC-8: only `CONFIRMED` commits; a revert releases, so it must not look confirmed."""
        order.mark_submitted("0x" + "aa" * 32, signed_amount)
        order.conclude(
            a_receipt(order_id=order.id, status=ReceiptStatus.REVERTED, revert_reason="BadSignature")
        )

        assert order.status is not SettlementStatus.CONFIRMED
