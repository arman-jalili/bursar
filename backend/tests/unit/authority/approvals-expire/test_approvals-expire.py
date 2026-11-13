"""A-14 — an approval expires; a stale signature cannot dispatch (AC 10).

Canonical: docs/contracts/authority-contract-freeze.md §1
Reference: .pi/architecture/modules/authority.md#components

An approval with no window is a standing authority, which is exactly what the mandate exists to prevent.
Expiry is checked at *both* signing and consumption, because the dangerous window is the one between them.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from src.authority.domain.approval import Approval, OwnerSignature
from src.authority.domain.errors import ApprovalExpired
from src.authority.domain.payment_intent import PaymentIntent
from tests.unit.authority._builders import (
    NOW,
    OWNER_ADDRESS,
    StubMandateView,
    an_attempt,
    an_invoice,
)


class TestApprovalsExpire:
    def test_verifying_after_the_window_raises(self) -> None:
        """A-14: a signature presented after expiry must be refused (AC 10)."""
        intent = PaymentIntent.issue(an_attempt(), StubMandateView(), an_invoice())
        approval = Approval.request(intent, expires_at=NOW - timedelta(minutes=1))

        with pytest.raises(ApprovalExpired):
            approval.verify(
                OwnerSignature(signature_hex="0xsig", signer=OWNER_ADDRESS),
                owner=OWNER_ADDRESS,
                now=NOW,
            )

    def test_consuming_after_the_window_raises(self) -> None:
        """A-14: expiry is re-checked at dispatch — signing in time is not dispatching in time."""
        intent = PaymentIntent.issue(an_attempt(), StubMandateView(), an_invoice())
        approval = Approval.request(intent, expires_at=NOW + timedelta(minutes=15))
        approval.verify(
            OwnerSignature(signature_hex="0xsig", signer=OWNER_ADDRESS),
            owner=OWNER_ADDRESS,
            now=NOW,
        )

        with pytest.raises(ApprovalExpired):
            approval.consume(now=NOW + timedelta(hours=1))

    def test_an_expired_refusal_does_not_consume_the_approval(self) -> None:
        """A-14/AC 12: a refused consume leaves no side effect, so the state is unchanged."""
        intent = PaymentIntent.issue(an_attempt(), StubMandateView(), an_invoice())
        approval = Approval.request(intent, expires_at=NOW + timedelta(minutes=15))

        with pytest.raises(ApprovalExpired):
            approval.consume(now=NOW + timedelta(hours=1))

        assert approval.consumed_at is None
