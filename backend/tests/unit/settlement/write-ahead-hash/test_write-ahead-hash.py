"""SC-3 — the transaction hash is written before broadcast, and there is only ever one.

Canonical: docs/contracts/settlement-contract-freeze.md §1 (SC-3)
Reference: .pi/architecture/modules/settlement.md#aggregate-settlementorder

Defends module AC #3: killing the process after `mark_submitted` and restarting must re-poll the same
hash. The unit-level half of that claim is here: the order refuses a different hash, keeps the first
one, and treats a repeated submit of the *same* hash as a re-poll rather than a new payment. The
integration half (a real restart) is Phase-B evidence.
"""

from __future__ import annotations

import pytest
from src.settlement.domain.errors import IllegalTransition, SecondTransactionRefused
from src.settlement.domain.values import SettlementStatus

from tests.unit.settlement._fixtures import a_receipt


class TestWriteAheadHash:
    def test_a_second_hash_is_refused(self, order, signed_amount) -> None:
        """SC-3 / AC-3: a second hash means a second nonce, which means a second payment."""
        order.mark_submitted("0x" + "aa" * 32, signed_amount)

        with pytest.raises(SecondTransactionRefused):
            order.mark_submitted("0x" + "bb" * 32, signed_amount)

    def test_the_first_hash_is_kept_after_the_refusal(self, order, signed_amount) -> None:
        """SC-3 / AC-3: refusing the second hash must not overwrite the write-ahead record."""
        first_hash = "0x" + "aa" * 32
        order.mark_submitted(first_hash, signed_amount)

        with pytest.raises(SecondTransactionRefused):
            order.mark_submitted("0x" + "bb" * 32, signed_amount)

        assert order.tx_hash == first_hash

    def test_re_polling_the_same_hash_after_a_restart_is_not_a_second_transaction(
        self, order, signed_amount
    ) -> None:
        """SC-3 / AC-3: re-submitting the persisted hash is a re-poll, so it must not be refused."""
        tx_hash = "0x" + "aa" * 32
        order.mark_submitted(tx_hash, signed_amount)

        order.mark_submitted(tx_hash, signed_amount)

        assert order.status is SettlementStatus.SUBMITTED

    def test_a_confirmed_order_cannot_be_submitted_again(self, order, signed_amount) -> None:
        """SC-3 / AC-3: once concluded there is no path back to the chain (SC-4)."""
        order.mark_submitted("0x" + "aa" * 32, signed_amount)
        order.conclude(a_receipt(order_id=order.id))

        with pytest.raises(IllegalTransition):
            order.mark_submitted("0x" + "bb" * 32, signed_amount)

    def test_the_hash_is_recorded_before_the_status_moves(self, order, signed_amount) -> None:
        """SC-3 / AC-3: the write-ahead ordering is observable — hash set, then SUBMITTED."""
        assert order.tx_hash is None

        order.mark_submitted("0x" + "aa" * 32, signed_amount)

        assert order.tx_hash == "0x" + "aa" * 32
        assert order.status is SettlementStatus.SUBMITTED
