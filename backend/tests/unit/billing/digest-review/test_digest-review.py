"""B-4 — the presented digest is stored for comparison only and never used for routing.

Canonical: docs/contracts/billing-contract-freeze.md §1
Reference: .pi/architecture/modules/billing.md#components-invoice

Scenario 2 lives here. The invoice carries a digest of the bank details *as printed on it*; Mandate
compares that against the payee's verified baseline and quarantines on mismatch. Billing's half of the
bargain is narrow and strict: keep the digest verbatim, and never let it decide where money goes — the
payee reference, not the document, is what Authority and Settlement act on.
"""

from __future__ import annotations

import pytest
from src.billing.domain.errors import BillingRefusal, DuplicateInvoice
from src.billing.domain.invoice import Invoice
from src.billing.domain.values import BilledAmount, InvoiceHash
from tests.unit.billing._fixtures import a_digest, a_document


class TestDigestReview:
    def test_the_presented_digest_is_kept_verbatim(self, payee_id, amount, due_date) -> None:
        """B-4: the digest as presented is what Mandate compares; normalising it would hide a mismatch.

        A digest that got re-derived from anything other than the document's own details could turn a
        poisoned invoice into a matching one, which is the entire scam.
        """
        poisoned = a_digest("GB33BUKB20201555555555")

        invoice = Invoice.from_document(
            payee_id=payee_id,
            amount=amount,
            due_date=due_date,
            document=a_document(),
            presented_digest=poisoned,
        )

        assert invoice.presented_digest.matches(poisoned)

    def test_the_payee_reference_comes_from_the_command_not_the_document(
        self, payee_id, amount, due_date
    ) -> None:
        """B-4: routing identity is the payee id; a document that names an address changes nothing.

        Asserting the *result* rather than the absence of a field: whatever the document says, the
        invoice's payee_id is the one the caller supplied from Mandate.
        """
        invoice = Invoice.from_document(
            payee_id=payee_id,
            amount=amount,
            due_date=due_date,
            document=a_document(bank_account="ATTACKER-123", payee_address="0xattacker"),
            presented_digest=a_digest("GB33BUKB20201555555555"),
        )

        assert invoice.payee_id == payee_id

    def test_a_mismatched_digest_still_records_the_bill(self, payee_id, amount, due_date) -> None:
        """B-4: Billing records the fact; the *refusal* happens in Mandate (quarantine) and Authority.

        Billing must not silently drop a poisoned invoice — the mismatch has to become evidence, which
        requires the bill to exist.
        """
        invoice = Invoice.from_document(
            payee_id=payee_id,
            amount=amount,
            due_date=due_date,
            document=a_document(),
            presented_digest=a_digest("GB33BUKB20201555555555"),
        )

        assert not invoice.presented_digest.matches(a_digest()), (
            "the stored digest must remain the presented one, so the mismatch stays detectable"
        )

    def test_a_duplicate_bill_is_refused_before_any_digest_review(
        self, payee_id, amount, due_date
    ) -> None:
        """B-4 + B-3: a replayed invoice is refused as a duplicate, not re-reviewed for its digest.

        Order matters: re-reviewing a replay would let the same bill re-open a payee that was quarantined
        because of it.
        """
        with pytest.raises(DuplicateInvoice):
            Invoice.from_document(
                payee_id=payee_id,
                amount=BilledAmount.from_usdc("42.50"),
                due_date=due_date,
                document=a_document(),
                presented_digest=a_digest(),
                existing_hashes=[InvoiceHash.from_document(a_document())],
            )

    def test_a_poisoned_digest_never_produces_a_routing_refusal(
        self, payee_id, amount, due_date
    ) -> None:
        """B-4: Billing must not refuse on the digest itself — that judgement belongs to Mandate.

        If Billing raised here, the two contexts would disagree about who decides eligibility and the
        evidence trail would name the wrong decider.
        """
        with pytest.raises(BillingRefusal):
            Invoice.from_document(
                payee_id=payee_id,
                amount=amount,
                due_date=due_date,  # type: ignore[arg-type]
                document=a_document(),
                presented_digest=a_digest("GB33BUKB20201555555555"),
                existing_hashes=[InvoiceHash.from_document(a_document())],
            )
