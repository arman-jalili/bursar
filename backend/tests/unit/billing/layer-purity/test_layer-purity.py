"""B-7 — every Billing refusal is a `RefusalError`, so a refusal can never look like a crash.

Canonical: docs/contracts/billing-contract-freeze.md §2.5
Reference: .pi/architecture/decisions/ADR-004-api-design.md

The "layer purity" this defends is the **refusal vocabulary's**: the domain raises the shared
`RefusalError` family and nothing else, so the API layer needs no Billing-specific exception handling and
a refusal always reaches the client as a documented `409` with a domain code. A `ValueError` escaping the
domain would become a `500` — the exact way an expected refusal gets reported as a server fault.

This file also refuses the opposite mistake: no `except Exception` swallowing, which would turn a refusal
into a silent no-op (the "no side effect" half of B-7).
"""

from __future__ import annotations

import pytest
from src.billing.domain.errors import (
    AmountMismatch,
    BillingRefusal,
    DuplicateInvoice,
    InvoiceAlreadySettled,
    InvoiceNotPayable,
    ProposalRejected,
)
from src.shared.domain.errors import RefusalError


class TestRefusalVocabulary:
    @pytest.mark.parametrize(
        "refusal",
        [
            DuplicateInvoice("abc"),
            InvoiceNotPayable("inv-1", "in_flight"),
            InvoiceAlreadySettled("inv-1"),
            ProposalRejected(("command",)),
            AmountMismatch("100", "250"),
        ],
    )
    def test_every_billing_refusal_is_a_shared_refusal(self, refusal: RefusalError) -> None:
        """B-7: one vocabulary — the envelope handler already knows how to render it."""
        assert isinstance(refusal, (RefusalError, BillingRefusal))

    def test_a_settled_invoice_refusal_is_a_kind_of_not_payable(self) -> None:
        """B-7: callers that handle 'not payable' also handle 'already settled' — no gap."""
        assert issubclass(InvoiceAlreadySettled, InvoiceNotPayable)

    def test_refusals_carry_a_reason_code(self) -> None:
        """B-7: the reason code is what the console translates and the evidence envelope seals."""
        assert ProposalRejected(("payee_address",)).reason_code

    def test_domain_refusal_is_raised_not_swallowed_at_the_entry_point(
        self, invoice, settled_invoice
    ) -> None:
        """B-7: the attempt factory must *raise*, never return a sentinel that a caller can ignore."""
        from src.billing.domain.payment_attempt import PaymentAttempt

        with pytest.raises(RefusalError):
            PaymentAttempt.from_proposal(
                {"invoice_id": settled_invoice.id, "payee_address": "0x1"}, settled_invoice
            )

        with pytest.raises(RefusalError):
            PaymentAttempt.from_proposal(
                {"invoice_id": invoice.id, "command": "payments.dispatch"}, invoice
            )
