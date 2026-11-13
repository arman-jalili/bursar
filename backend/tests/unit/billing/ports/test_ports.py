"""B-6 / B-3 — the ports accept and return the domain's own types, and refuse edited amounts.

Canonical: docs/contracts/billing-contract-freeze.md §2.6
Reference: .pi/architecture/modules/billing.md#components

A port that took a `dict` or an ORM row would put the amount-equality rule (B-6) and the hash-identity
rule (B-3) at the mercy of whoever builds that structure. The assertions below are about *rules the port
must preserve*, not about method names: an attempt must carry the invoice's exact amount, and an invoice
must keep the hash it was recorded with.
"""

from __future__ import annotations

import pytest
from src.billing.domain.errors import AmountMismatch
from src.billing.domain.payment_attempt import PaymentAttempt
from src.billing.domain.values import AttemptStatus, BilledAmount


class TestPorts:
    def test_an_attempt_cannot_carry_a_different_amount_than_the_invoice(self, invoice) -> None:
        """B-6: a proposal that edits the amount is refused, so no port can persist a mismatch.

        This is the split-invoice defence: six 25 USDC attempts against a 150 USDC cap only work if the
        amounts are editable on the way in.
        """
        with pytest.raises(AmountMismatch):
            PaymentAttempt.from_proposal(
                {"invoice_id": invoice.id, "proposed_amount_micro_usdc": 25_000_000}, invoice
            )

    def test_an_attempt_carrying_the_invoice_amount_is_accepted(self, invoice) -> None:
        """B-6: the guard must accept the honest case, including an omitted amount."""
        attempt = PaymentAttempt.from_proposal({"invoice_id": invoice.id}, invoice)

        assert attempt.status is AttemptStatus.PROPOSED

    def test_the_attempt_keeps_the_invoice_identity(self, invoice) -> None:
        """B-3: the port groups attempts by invoice id, so the attempt must carry exactly that id."""
        attempt = PaymentAttempt.from_proposal({"invoice_id": invoice.id}, invoice)

        assert attempt.invoice_id == invoice.id

    def test_an_invoice_keeps_its_recorded_hash(self, invoice) -> None:
        """B-3: the hash is the insert key and the nullifier seed — it must survive recording intact."""
        from src.billing.domain.values import InvoiceHash

        assert invoice.hash.same_as(InvoiceHash.from_document({"issuer": "Northwind Energy"}))

    def test_amount_equality_is_exact(self) -> None:
        """B-6: 42.50 must not equal 42.499999, or a threshold check could be split by rounding."""
        assert BilledAmount.from_usdc("42.50").same_as(BilledAmount(micro_usdc=42_500_000))
        assert not BilledAmount.from_usdc("42.50").same_as(BilledAmount(micro_usdc=42_499_999))
