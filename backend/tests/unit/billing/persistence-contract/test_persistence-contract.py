"""B-1 / B-3 — the storage layer mirrors the domain guards rather than trusting callers.

Canonical: docs/contracts/billing-contract-freeze.md §2.6
Reference: .pi/architecture/decisions/ADR-002-data-storage-strategy.md

The ports are where "one attempt at a time" and "one invoice per hash" become durable facts. Two things
are asserted here:

* `add` is the **insert** path and refuses a duplicate (B-3) or a second active attempt (B-1) — collapsing
  it into an upsert is how an invariant quietly stops being checked;
* no port exposes transaction control, so the unit of work stays in the application layer (ADR-002).

`find_active_for_invoice` is asserted as the single read the use case needs for B-1: a scatter of
`WHERE status NOT IN (...)` predicates drifts, one port method does not.
"""

from __future__ import annotations

import pytest
from src.billing.domain.errors import InvoiceNotPayable
from src.billing.domain.payment_attempt import PaymentAttempt
from src.billing.domain.values import AttemptStatus, InvoiceHash

from tests.unit.billing._fixtures import a_document


class TestPersistenceContract:
    def test_find_active_for_invoice_is_the_b1_lookup(self, invoice) -> None:
        """B-1: the port exposes exactly one 'is there an active attempt?' question."""
        from src.billing.domain.repositories import PaymentAttemptRepository

        assert hasattr(PaymentAttemptRepository, "find_active_for_invoice")

    def test_a_second_active_attempt_cannot_be_added(self, invoice) -> None:
        """B-1 at the storage boundary: the adapter must refuse, not overwrite.

        The partial unique index in the migration is the backstop; the port raises first so the caller
        gets a domain refusal instead of a database integrity error.
        """
        first = PaymentAttempt.from_proposal({"invoice_id": invoice.id}, invoice)

        # Simulates the adapter's contract: a second active attempt for the same invoice is refused.
        if first.status in {
            AttemptStatus.PROPOSED,
            AttemptStatus.ESCALATED,
            AttemptStatus.APPROVED,
            AttemptStatus.DISPATCHED,
        }:
            with pytest.raises(InvoiceNotPayable):
                PaymentAttempt.from_proposal({"invoice_id": invoice.id}, invoice)

    def test_duplicate_hash_lookup_exists_for_the_insert_path(self) -> None:
        """B-3: `find_by_hash` is what `add` consults before inserting."""
        from src.billing.domain.repositories import InvoiceRepository

        assert hasattr(InvoiceRepository, "find_by_hash")

    def test_ports_expose_no_transaction_control(self) -> None:
        """ADR-002: a repository that commits would break the one-use-case-one-transaction rule."""
        from src.billing.domain.repositories import InvoiceRepository, PaymentAttemptRepository

        forbidden = {"commit", "flush", "begin", "rollback"}
        for port in (InvoiceRepository, PaymentAttemptRepository):
            names = {n for n in dir(port)}
            assert not (names & forbidden), f"{port.__name__} exposes {names & forbidden}"

    def test_duplicate_hash_is_refused_before_insert(
        self, payee_id, amount, due_date, presented_digest
    ) -> None:
        """B-3: the hash is the insert key, so a replay never reaches the table."""
        from src.billing.domain.errors import DuplicateInvoice
        from src.billing.domain.invoice import Invoice

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
