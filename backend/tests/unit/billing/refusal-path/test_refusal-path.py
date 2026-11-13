"""B-7 — only an allow or escalate determination dispatches; a refusal is terminal and side-effect free.

Canonical: docs/contracts/billing-contract-freeze.md §1
Reference: .pi/architecture/modules/billing.md#components-paymentattempt

The most consequential rule in this context. A refused attempt must (a) never reach `DISPATCHED`, and
(b) stay terminal, so nothing retries it implicitly. Both halves are asserted, because "refused but
dispatchable" and "refused but re-openable" are different bugs with the same cost.
"""

from __future__ import annotations

import pytest

from src.billing.domain.errors import BillingRefusal
from src.billing.domain.payment_attempt import PaymentAttempt
from src.billing.domain.values import AttemptStatus


class TestRefusalPath:
    @pytest.mark.parametrize("determination", ["deny", "refused", "cap_exceeded", "payee_frozen"])
    def test_a_refusal_determination_cannot_dispatch(self, invoice, determination: str) -> None:  # noqa: ANN001
        """B-7: any non-allow verdict raises instead of moving the attempt forward."""
        attempt = PaymentAttempt.from_proposal({"invoice_id": invoice.id}, invoice)

        with pytest.raises(BillingRefusal):
            attempt.mark_dispatched(determination=determination)

    def test_an_allow_determination_dispatches(self, invoice) -> None:  # noqa: ANN001
        """B-7: the positive case must still work, or the guard is just a wall."""
        attempt = PaymentAttempt.from_proposal({"invoice_id": invoice.id}, invoice)
        attempt.mark_dispatched(determination="allow")

        assert attempt.status is AttemptStatus.DISPATCHED

    def test_an_escalate_determination_may_dispatch_once_approved(self, invoice) -> None:  # noqa: ANN001
        """B-7: escalation is not a refusal — the owner signature is what unlocks dispatch."""
        attempt = PaymentAttempt.from_proposal({"invoice_id": invoice.id}, invoice)
        attempt.mark_dispatched(determination="escalate")

        assert attempt.status is AttemptStatus.DISPATCHED

    def test_a_refused_attempt_cannot_be_dispatched_afterwards(self, invoice) -> None:  # noqa: ANN001
        """B-7: terminal means terminal — a later allow determination must not revive it.

        This is the recovery-from-timeout bug: the payment failed, the retry loop was slow, and the
        attempt gets dispatched anyway.
        """
        attempt = PaymentAttempt.from_proposal({"invoice_id": invoice.id}, invoice)
        attempt.mark_refused("cap_exceeded")

        with pytest.raises(BillingRefusal):
            attempt.mark_dispatched(determination="allow")
