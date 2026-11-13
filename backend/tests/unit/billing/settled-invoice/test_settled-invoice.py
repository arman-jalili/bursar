"""B-2 — an invoice whose attempt settled is closed and cannot spawn further attempts.

Canonical: docs/contracts/billing-contract-freeze.md §1
Reference: .pi/architecture/modules/billing.md#components-invoice

Scenario 6: the bill was paid, a replay arrives later. The invoice must refuse to close twice (that
would hide a duplicate settlement) and must refuse new attempts forever.
"""

from __future__ import annotations

import pytest

from src.billing.domain.errors import InvoiceAlreadySettled, InvoiceNotPayable
from src.billing.domain.invoice import Invoice
from src.billing.domain.payment_attempt import PaymentAttempt
from src.billing.domain.values import InvoiceStatus


class TestSettledInvoice:
    def test_settling_twice_raises_instead_of_being_idempotent(self, settled_invoice) -> None:  # noqa: ANN001
        """B-2: a second settlement is a bug, not a no-op.

        Making it idempotent would let a duplicate on-chain settlement look routine in the logs, which is
        precisely the event an auditor must see fail loudly.
        """
        with pytest.raises(InvoiceAlreadySettled):
            settled_invoice.mark_settled()

    def test_a_settled_invoice_accepts_no_further_attempt(self, settled_invoice) -> None:  # noqa: ANN001
        """B-2: proposing against a closed bill raises InvoiceNotPayable."""
        with pytest.raises(InvoiceNotPayable):
            PaymentAttempt.from_proposal({"invoice_id": settled_invoice.id}, settled_invoice)

    def test_settling_moves_the_invoice_to_settled(self, invoice) -> None:  # noqa: ANN001
        """B-2: the only way into SETTLED is mark_settled, and it lands there."""
        invoice.mark_settled()

        assert invoice.status is InvoiceStatus.SETTLED

    def test_recording_the_same_bill_after_settlement_still_refuses(self, settled_invoice, payee_id, amount, due_date, presented_digest) -> None:  # noqa: ANN001
        """B-2 + B-3: a settled bill is still the same bill — a replay is a duplicate, not a new debt."""
        from src.billing.domain.errors import DuplicateInvoice

        with pytest.raises(DuplicateInvoice):
            Invoice.record(
                payee_id=payee_id,
                amount=amount,
                due_date=settled_invoice.due_date,
                document={"issuer": "Northwind Energy"},  # unrelated document, same hash source
                presented_digest=presented_digest,
                existing_hashes=[settled_invoice.hash],
            )
