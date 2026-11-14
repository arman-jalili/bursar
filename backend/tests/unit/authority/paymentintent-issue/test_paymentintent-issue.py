"""A-2 / A-3 — the intent takes routing from Mandate and the amount from the invoice (AC 1, AC 2).

Canonical: docs/contracts/authority-contract-freeze.md §1
Reference: docs/architecture/modules/authority.md#aggregate-paymentintent

The anti-injection rule and the anti-split rule, in one place. Both are asserted by *outcome*: what the
intent ends up carrying, not which fields the caller sent.
"""

from __future__ import annotations

import pytest
from src.authority.domain.errors import AuthorityRefusal
from src.authority.domain.payment_intent import PaymentIntent
from tests.unit.authority._builders import StubMandateView, a_payee, an_attempt, an_invoice


class TestPaymentIntentIssue:
    def test_the_intent_uses_mandate_address_not_the_proposals(self) -> None:
        """A-2: whatever the attempt claims, the destination is Mandate's verified address (AC 1)."""
        mandate = StubMandateView(payee=a_payee())

        intent = PaymentIntent.issue(an_attempt(), mandate, an_invoice())

        assert intent.payee_address.value == "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
        assert intent.payee_address.value != "0xATTACKER000000000000000000000000000000"

    def test_the_intent_uses_mandates_verified_digest(self) -> None:
        """A-2: the digest on the intent is the verified baseline, so a poisoned invoice cannot retarget."""
        mandate = StubMandateView(payee=a_payee(account="DE89370400440532013000"))

        intent = PaymentIntent.issue(an_attempt(), mandate, an_invoice())

        assert intent.bank_digest.matches(a_payee(account="DE89370400440532013000").digest)

    def test_a_claimed_amount_that_differs_from_the_invoice_is_refused(self) -> None:
        """A-3: an attempt may not edit the amount — that is how one bill is split under a threshold."""
        with pytest.raises(AuthorityRefusal):
            PaymentIntent.issue(
                an_attempt(claimed="25.00"), StubMandateView(), an_invoice(amount="42.50")
            )

    def test_the_amount_comes_from_the_invoice_when_none_is_claimed(self) -> None:
        """A-3: the invoice is the source of truth, so an honest attempt needs no amount at all."""
        intent = PaymentIntent.issue(an_attempt(), StubMandateView(), an_invoice(amount="42.50"))

        assert intent.amount == an_invoice(amount="42.50").amount

    def test_issuing_reads_mandate_at_decision_time(self) -> None:
        """A-2/A-6: the port is consulted while issuing, never replaced by a cached view."""
        mandate = StubMandateView()

        PaymentIntent.issue(an_attempt(), mandate, an_invoice())

        assert ("payee", "payee-1") in mandate.calls
