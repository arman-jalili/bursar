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
from src.shared.domain.errors import ValidationError

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


class TestSignThenBroadcast:
    """SC-3 with a two-phase port: the hash exists before anything is sent, and in its own state."""

    def test_marking_signed_persists_the_hash_and_the_bytes_before_any_broadcast(
        self, order, signed_amount
    ) -> None:
        """Signing is local, so the hash is a write-ahead fact — and the bytes must travel with it."""
        raw = "0x02f8" + "ab" * 60
        tx_hash = "0x" + "aa" * 32

        order.mark_signed(tx_hash, raw, signed_amount)

        assert order.tx_hash == tx_hash
        assert order.raw_transaction == raw
        assert order.status is SettlementStatus.SIGNED
        # Nothing was broadcast, so nothing claims to have been: no `SettlementSubmitted` yet.
        assert order.pull_events() == ()

    def test_the_governed_step_moves_the_same_hash_to_submitted(self, order, signed_amount) -> None:
        """Broadcast is the *same* hash arriving in a later state, never a new transaction (SC-3)."""
        tx_hash = "0x" + "aa" * 32
        order.mark_signed(tx_hash, "0x02f8" + "ab" * 60, signed_amount)

        order.mark_submitted(tx_hash, signed_amount)

        assert order.status is SettlementStatus.SUBMITTED
        assert order.tx_hash == tx_hash
        assert [event.event_name for event in order.pull_events()] == ["SettlementSubmitted"]

    def test_a_second_signature_for_a_signed_order_is_refused(self, order, signed_amount) -> None:
        """SC-3: re-signing a signed order takes a new nonce — the double-payment path, closed."""
        order.mark_signed("0x" + "aa" * 32, "0x02f8" + "ab" * 60, signed_amount)

        with pytest.raises(SecondTransactionRefused):
            order.mark_signed("0x" + "bb" * 32, "0x02f8" + "cd" * 60, signed_amount)

        assert order.tx_hash == "0x" + "aa" * 32

    def test_signing_bytes_that_are_not_hex_is_refused(self, order, signed_amount) -> None:
        """A value the node could not accept must never be stored as if it were a signed payment."""
        with pytest.raises(ValidationError):
            order.mark_signed("0x" + "aa" * 32, "not-a-transaction", signed_amount)

        assert order.tx_hash is None
        assert order.status is SettlementStatus.ORDERED

    def test_a_signed_order_with_a_receipt_can_conclude(self, order, signed_amount) -> None:
        """Recovery: a process that died before the broadcast is resolved by the persisted hash."""
        tx_hash = "0x" + "aa" * 32
        order.mark_signed(tx_hash, "0x02f8" + "ab" * 60, signed_amount)

        order.conclude(a_receipt(order_id=order.id))

        assert order.status is SettlementStatus.CONFIRMED
