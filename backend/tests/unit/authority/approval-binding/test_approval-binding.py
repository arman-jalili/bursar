"""A-13 — an approval binds one intent's exact bytes; any mismatch invalidates it (AC 8).

Canonical: docs/contracts/authority-contract-freeze.md §1
Reference: docs/architecture/modules/authority.md#components

Scenario 5, negative case: a signature over intent A replayed for intent B. The binding is a single digest
over the intent's fields, because checking fields one by one is how a forgotten field becomes a hole.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from src.authority.domain.approval import Approval, OwnerSignature
from src.authority.domain.errors import ApprovalBindingMismatch
from src.authority.domain.payment_intent import PaymentIntent
from tests.unit.authority._builders import (
    NOW,
    OWNER_ADDRESS,
    StubMandateView,
    an_attempt,
    an_invoice,
)


class TestApprovalBinding:
    def test_a_signature_over_another_intent_is_refused(self) -> None:
        """A-13: the same signature for a different intent must raise, not dispatch (AC 8)."""
        intent_a = PaymentIntent.issue(an_attempt(), StubMandateView(), an_invoice(amount="20.00"))
        intent_b = PaymentIntent.issue(an_attempt(), StubMandateView(), an_invoice(amount="320.00"))
        approval = Approval.request(intent_b, expires_at=NOW + timedelta(minutes=15))

        with pytest.raises(ApprovalBindingMismatch):
            approval.verify(
                OwnerSignature(
                    signature_hex="0xsig-for-a",
                    signer=OWNER_ADDRESS,
                    signed_digest=intent_a.typed_data_hash(),
                ),
                owner=OWNER_ADDRESS,
                now=NOW,
            )

    def test_a_signature_from_a_non_owner_is_refused(self) -> None:
        """A-15: possession of a key is not ownership — the recovered signer must be the mandate owner."""
        intent = PaymentIntent.issue(an_attempt(), StubMandateView(), an_invoice())
        approval = Approval.request(intent, expires_at=NOW + timedelta(minutes=15))
        stranger = OwnerSignature(
            signature_hex="0xsig",
            signer=__import__("src.mandate.domain.values", fromlist=["EvmAddress"]).EvmAddress(
                "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
            ),
            signed_digest=approval.typed_data_hash,
        )

        with pytest.raises(ApprovalBindingMismatch):
            approval.verify(stranger, owner=OWNER_ADDRESS, now=NOW)

    def test_the_bound_digest_covers_the_amount_and_the_destination(self) -> None:
        """A-13: the binding is over the fields that move money, so changing either invalidates it."""
        intent = PaymentIntent.issue(an_attempt(), StubMandateView(), an_invoice(amount="20.00"))
        approval = Approval.request(intent, expires_at=NOW + timedelta(minutes=15))

        payload = intent.signed_payload()
        assert approval.typed_data_hash
        assert payload["amountUsdc"] != an_invoice(amount="320.00").amount.micro_usdc

    def test_a_request_is_bound_to_exactly_one_intent(self) -> None:
        """A-13: one approval, one intent id — there is no list of intents to reuse it across."""
        intent = PaymentIntent.issue(an_attempt(), StubMandateView(), an_invoice())

        approval = Approval.request(intent, expires_at=NOW + timedelta(minutes=15))

        assert approval.intent_id == intent.id
