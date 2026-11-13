"""B-3 / B-6 — the invoice hash is deterministic, and the amount is exact.

Canonical: docs/contracts/billing-contract-freeze.md §1
Reference: .pi/architecture/modules/billing.md#components-invoice

Two rules that both exist to stop the invoice identity from being negotiable: the hash of the same
document must be stable (B-3), and an amount must be exactly representable or refused (B-6).
"""

from __future__ import annotations

import pytest

from src.billing.domain.values import BilledAmount, InvoiceHash

from tests.unit.billing._fixtures import a_document


class TestInvoiceHash:
    def test_same_document_hashes_the_same_across_calls(self) -> None:
        """B-3: determinism is the whole contract — a hash that drifts cannot be the duplicate key."""
        first = InvoiceHash.from_document(a_document())
        second = InvoiceHash.from_document(a_document())

        assert first.same_as(second)

    def test_an_altered_field_changes_the_hash(self) -> None:
        """B-3: one changed character means a different bill, so the hashes must differ."""
        original = InvoiceHash.from_document(a_document())
        altered = InvoiceHash.from_document(a_document(amount_usdc="43.50"))

        assert not original.same_as(altered)

    def test_an_empty_document_is_refused(self) -> None:
        """B-3: hashing nothing would make every empty document the same bill."""
        from src.billing.domain.errors import BillingRefusal

        with pytest.raises(BillingRefusal):
            InvoiceHash.from_document({})


class TestBilledAmount:
    def test_exact_usdc_parses_to_micro_units(self) -> None:
        """B-6: 42.50 USDC is 42_500_000 micro-units — no float, no rounding."""
        assert BilledAmount.from_usdc("42.50").same_as(BilledAmount(micro_usdc=42_500_000))

    def test_float_input_is_refused(self) -> None:
        """B-6: accepting a float would let an edited amount compare equal to the invoice."""
        from src.billing.domain.errors import BillingRefusal

        with pytest.raises(BillingRefusal):
            BilledAmount.from_usdc(42.50)  # type: ignore[arg-type]

    def test_negative_and_zero_amounts_are_refused(self) -> None:
        """B-6: an invoice for nothing, or for minus something, is not a bill."""
        from src.billing.domain.errors import BillingRefusal

        for bad in ("0", "-1", "-0.01"):
            with pytest.raises(BillingRefusal):
                BilledAmount.from_usdc(bad)
