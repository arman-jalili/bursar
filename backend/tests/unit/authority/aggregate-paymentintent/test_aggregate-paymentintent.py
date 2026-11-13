"""A-1 — an issued intent is immutable: no setter, no merge, no late mutation.

Canonical: docs/contracts/authority-contract-freeze.md §1
Reference: .pi/architecture/modules/authority.md#aggregate-paymentintent

The window between authorization and signature is exactly where a substituted destination would pay off,
so the intent must not be mutable at all. Asserted by attempting the mutation a careless adapter would do
and requiring it to be refused.
"""

from __future__ import annotations

import pytest
from src.authority.domain.payment_intent import PaymentIntent
from tests.unit.authority._builders import StubMandateView, an_attempt, an_invoice


class TestPaymentIntentImmutability:
    def test_an_issued_intent_refuses_field_assignment(self) -> None:
        """A-1: assigning a field after issue is refused, so nothing can retarget it."""
        intent = PaymentIntent.issue(an_attempt(), StubMandateView(), an_invoice())

        with pytest.raises(AttributeError):
            intent.amount = an_invoice(amount="320.00").amount

    def test_an_issued_intent_refuses_a_bulk_merge(self) -> None:
        """A-1: no `update()`/`merge()` — a bulk patch would bypass every invariant at once."""
        intent = PaymentIntent.issue(an_attempt(), StubMandateView(), an_invoice())

        for method in ("update", "merge", "apply"):
            if hasattr(intent, method):
                with pytest.raises((AttributeError, TypeError)):
                    getattr(intent, method)({"amount": 1})

    def test_two_intents_for_the_same_invoice_are_different_intents(self) -> None:
        """A-1: identity, not state — two intents of one bill must not compare equal."""
        first = PaymentIntent.issue(an_attempt(), StubMandateView(), an_invoice())
        second = PaymentIntent.issue(an_attempt(), StubMandateView(), an_invoice())

        assert first != second

    def test_the_signed_payload_is_the_authoritative_field_set(self) -> None:
        """A-1/A-13: one payload definition, because the owner signs these exact bytes."""
        intent = PaymentIntent.issue(an_attempt(), StubMandateView(), an_invoice())

        payload = intent.signed_payload()

        assert set(payload) >= {"intentId", "invoiceId", "payeeAddress", "amountUsdc", "bankDigest"}
        assert payload["payeeAddress"] == intent.payee_address.value
