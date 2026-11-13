"""B-1 — an invoice has at most one non-terminal payment attempt at a time.

Canonical: docs/contracts/billing-contract-freeze.md §1
Reference: .pi/architecture/modules/billing.md#components-paymentattempt

Defends the invariant that stops two concurrent proposals from racing one invoice into a double payment.
The rule is enforced at two points and both are asserted here: the invoice must say it cannot accept an
attempt, and the attempt factory must refuse to build a second one even if the caller ignores that.
"""

from __future__ import annotations

import pytest
from src.billing.domain.errors import InvoiceNotPayable
from src.billing.domain.payment_attempt import PaymentAttempt


class TestAtMostOneAttempt:
    def test_second_attempt_on_an_invoice_with_one_in_flight_is_refused(self, invoice) -> None:
        """B-1: a second proposal for the same invoice must raise InvoiceNotPayable.

        Two bills of the same invoice paid twice is the classic timeout double-pay; the guard belongs
        here, before Authority is ever asked.
        """
        PaymentAttempt.from_proposal({"invoice_id": invoice.id}, invoice)

        with pytest.raises(InvoiceNotPayable):
            PaymentAttempt.from_proposal({"invoice_id": invoice.id}, invoice)

    def test_invoice_reports_it_cannot_accept_an_attempt(self, invoice) -> None:
        """B-1: `can_accept_attempt` is the single query the use case asks before proposing."""
        PaymentAttempt.from_proposal({"invoice_id": invoice.id}, invoice)

        assert invoice.can_accept_attempt() is False

    def test_refused_attempt_frees_the_invoice_for_a_new_proposal(self, invoice) -> None:
        """B-1 vs B-7: a *refused* attempt is terminal, so the invoice is outstanding again.

        The distinction matters: a refusal must not lock the bill, or a legitimate retry becomes
        impossible and the household cannot pay at all.
        """
        from src.billing.domain.values import AttemptStatus

        attempt = PaymentAttempt.from_proposal({"invoice_id": invoice.id}, invoice)
        attempt.mark_refused("payee_quarantined")

        assert attempt.status is AttemptStatus.REFUSED
        assert invoice.can_accept_attempt() is True
        PaymentAttempt.from_proposal({"invoice_id": invoice.id}, invoice)
