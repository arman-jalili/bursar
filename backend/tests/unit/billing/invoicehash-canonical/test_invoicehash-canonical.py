"""B-3 / AC #1 — the invoice hash is canonical across fields, not just across calls.

Canonical: docs/architecture/modules/billing.md#acceptance-criteria
Reference: docs/contracts/billing-contract-freeze.md (B-3)

The freeze suite proves the hash is stable and that an amount change is detected. This suite closes
the other half of AC #1: a one-character change to **any** identity field is a different bill, and a
re-serialised document (field order) is the same bill. If a field could drift without changing the
hash, a replay of an edited invoice would pass the duplicate check.
"""

from __future__ import annotations

import pytest
from src.billing.domain.values import InvoiceHash
from tests.unit.billing._fixtures import a_document

IDENTITY_FIELDS = ("issuer", "invoice_number", "amount_usdc", "due_date")


class TestCanonicalInvoiceHash:
    @pytest.mark.parametrize("field", IDENTITY_FIELDS)
    def test_one_changed_character_in_any_field_is_a_different_bill(self, field: str) -> None:
        """AC #1: same document → same hash; one changed character → different hash."""
        original = InvoiceHash.from_document(a_document())
        altered_value = f"{a_document()[field]}X"
        altered = InvoiceHash.from_document(a_document(**{field: altered_value}))

        assert not original.same_as(altered), f"changing {field} must change the bill's identity"

    def test_field_order_is_not_identity(self) -> None:
        """B-3: a re-serialised document is the same bill — dict order is a producer detail."""
        reordered = dict(reversed(list(a_document().items())))
        assert InvoiceHash.from_document(a_document()).same_as(InvoiceHash.from_document(reordered))

    def test_the_same_document_is_stable_across_calls(self) -> None:
        assert InvoiceHash.from_document(a_document()) == InvoiceHash.from_document(a_document())

    def test_nested_values_are_canonicalised(self) -> None:
        """A nested mapping is not a loophole: the same content in a different order is the same bill."""
        left = InvoiceHash.from_document(
            a_document(meta={"b": 2, "a": 1}, lines=[{"qty": 1, "price": "42.50"}])
        )
        right = InvoiceHash.from_document(
            a_document(meta={"a": 1, "b": 2}, lines=[{"price": "42.50", "qty": 1}])
        )

        assert left.same_as(right)
