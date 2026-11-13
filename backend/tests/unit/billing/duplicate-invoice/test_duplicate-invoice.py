"""B-3 — an invoice hash identifies the bill: a second identical hash is the same invoice.

Canonical: docs/contracts/billing-contract-freeze.md §1
Reference: .pi/architecture/modules/billing.md#components-invoice

A replay must not enter the funnel as new demand: if it did, the cap ledger would happily pay the same
bill twice. The rule is asserted at the recording point, which is the earliest place it can be caught.
"""

from __future__ import annotations

import pytest
from src.billing.domain.errors import DuplicateInvoice
from src.billing.domain.invoice import Invoice
from src.billing.domain.values import InvoiceHash
from tests.unit.billing._fixtures import a_document


class TestDuplicateInvoice:
    def test_recording_a_known_hash_raises_duplicate_invoice(
        self, payee_id, amount, due_date, presented_digest
    ) -> None:
        """B-3: the same document recorded twice must raise DuplicateInvoice, not create a second bill."""
        known = InvoiceHash.from_document(a_document())

        with pytest.raises(DuplicateInvoice):
            Invoice.from_document(
                payee_id=payee_id,
                amount=amount,
                due_date=due_date,
                document=a_document(),
                presented_digest=presented_digest,
                existing_hashes=[known],
            )

    def test_a_one_character_change_is_a_different_bill(
        self, payee_id, amount, due_date, presented_digest
    ) -> None:
        """B-3: 'INV-2026-0042' and 'INV-2026-0043' are different bills, so recording must succeed.

        If this raised, a household could never pay two genuinely different invoices from one issuer.
        """
        known = InvoiceHash.from_document(a_document())

        Invoice.from_document(
            payee_id=payee_id,
            amount=amount,
            due_date=due_date,
            document=a_document(invoice_number="INV-2026-0043"),
            presented_digest=presented_digest,
            existing_hashes=[known],
        )

    def test_duplicate_detection_does_not_depend_on_key_order(
        self, payee_id, amount, due_date, presented_digest
    ) -> None:
        """B-3: the hash is canonical, so a re-serialised document is still the same bill.

        Dict ordering is not stable across producers; a hash that changed with it would let the same
        invoice through twice just by re-encoding it.
        """
        reordered = dict(reversed(list(a_document().items())))
        known = InvoiceHash.from_document(reordered)

        with pytest.raises(DuplicateInvoice):
            Invoice.from_document(
                payee_id=payee_id,
                amount=amount,
                due_date=due_date,
                document=a_document(),
                presented_digest=presented_digest,
                existing_hashes=[known],
            )
