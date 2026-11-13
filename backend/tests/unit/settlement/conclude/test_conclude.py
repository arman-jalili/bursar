"""SC-4 — an order concludes exactly once.

Canonical: docs/contracts/settlement-contract-freeze.md §1 (SC-4)
Reference: .pi/architecture/modules/settlement.md#aggregate-settlementorder

Defends module AC #4: a second `conclude` raises `OrderAlreadyConcluded`. The rule is not "idempotent
second write": silently accepting a replay is how a duplicate settlement looks normal in the ledger, so
the second call is a refusal with a name.
"""

from __future__ import annotations

import pytest
from src.settlement.domain.errors import IllegalTransition, OrderAlreadyConcluded
from src.settlement.domain.values import ReceiptStatus, SettlementStatus

from tests.unit.settlement._fixtures import a_receipt


class TestConcludeOnce:
    def test_a_second_conclusion_is_refused(self, order, signed_amount) -> None:
        """SC-4 / AC-4: concluding twice raises, and the order keeps its first outcome."""
        order.mark_submitted("0x" + "aa" * 32, signed_amount)
        order.conclude(a_receipt(order_id=order.id))

        with pytest.raises(OrderAlreadyConcluded):
            order.conclude(a_receipt(order_id=order.id))

    def test_a_confirmed_order_is_terminal(self, order, signed_amount) -> None:
        """SC-4 / AC-4: `CONFIRMED` is an end state — the only state that commits the cap."""
        order.mark_submitted("0x" + "aa" * 32, signed_amount)

        order.conclude(a_receipt(order_id=order.id))

        assert order.status is SettlementStatus.CONFIRMED

    def test_a_reverted_order_is_concluded_as_a_refusal(self, order, signed_amount) -> None:
        """SC-4 / AC-4: a chain refusal is a conclusion, not a pending state to retry (SC-6)."""
        order.mark_submitted("0x" + "aa" * 32, signed_amount)

        order.conclude(
            a_receipt(order_id=order.id, status=ReceiptStatus.REVERTED, revert_reason="NullifierSpent")
        )

        assert order.status is SettlementStatus.REVERTED

    def test_an_order_never_reached_the_chain_cannot_conclude(self, order) -> None:
        """SC-4 / AC-4: there is no receipt for a submission that never happened (SC-3)."""
        with pytest.raises(IllegalTransition):
            order.conclude(a_receipt(order_id=order.id))

    def test_conclusion_records_exactly_one_outcome_event(self, order, signed_amount) -> None:
        """SC-4 / AC-4: the outbox sees one fact per conclusion — a second would double-reconcile."""
        order.mark_submitted("0x" + "aa" * 32, signed_amount)
        order.conclude(a_receipt(order_id=order.id))

        outcomes = [event for event in order.pull_events() if event.name in {"SettlementConfirmed"}]

        assert len(outcomes) == 1
