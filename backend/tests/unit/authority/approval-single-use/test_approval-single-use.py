"""A-14 — an approval is single-use: one signature cannot dispatch twice (AC 9).

Canonical: docs/contracts/authority-contract-freeze.md §1
Reference: .pi/architecture/modules/authority.md#components

A reused signature is the cheapest way to double-pay: the owner signed once, the retry loop dispatched
twice. `consume()` is therefore one-way with no `reset()`.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from src.authority.domain.approval import Approval, OwnerSignature
from src.authority.domain.errors import ApprovalSingleUse
from src.authority.domain.payment_intent import PaymentIntent
from tests.unit.authority._builders import (
    NOW,
    OWNER_ADDRESS,
    StubMandateView,
    an_attempt,
    an_invoice,
)


class TestApprovalSingleUse:
    def test_consuming_twice_raises(self) -> None:
        """A-14: the second consume must raise, so only one settlement can follow one signature (AC 9)."""
        intent = PaymentIntent.issue(an_attempt(), StubMandateView(), an_invoice())
        approval = Approval.request(intent, expires_at=NOW + timedelta(minutes=15))
        approval.verify(
            OwnerSignature(signature_hex="0xsig", signer=OWNER_ADDRESS),
            owner=OWNER_ADDRESS,
            now=NOW,
        )
        approval.consume(now=NOW)

        with pytest.raises(ApprovalSingleUse):
            approval.consume(now=NOW)

    def test_a_consumed_approval_is_not_usable(self) -> None:
        """A-14: `is_usable` is the dispatch precondition, so it must flip after consumption."""
        intent = PaymentIntent.issue(an_attempt(), StubMandateView(), an_invoice())
        approval = Approval.request(intent, expires_at=NOW + timedelta(minutes=15))
        approval.verify(
            OwnerSignature(signature_hex="0xsig", signer=OWNER_ADDRESS),
            owner=OWNER_ADDRESS,
            now=NOW,
        )
        approval.consume(now=NOW)

        assert approval.is_usable is False

    def test_there_is_no_way_to_reset_an_approval(self) -> None:
        """A-14: a reset would restore a spent signature — there is deliberately no such method."""
        intent = PaymentIntent.issue(an_attempt(), StubMandateView(), an_invoice())
        approval = Approval.request(intent, expires_at=NOW + timedelta(minutes=15))

        assert not hasattr(approval, "reset")
        assert not hasattr(approval, "reopen")
