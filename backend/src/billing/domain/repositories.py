"""Billing repository ports — owned by `domain/` (frozen).

Canonical: docs/architecture/modules/billing.md#components
Reference: docs/contracts/billing-contract-freeze.md §2.6

    InvoiceRepository          add (B-3 duplicate guard) · find_by_id · find_by_hash · save
    PaymentAttemptRepository   add (B-1 active guard)    · find_by_id · find_active_for_invoice

Two rules are expressed by the signatures rather than left to convention:

1. **No transaction control.** No `commit`, `flush` or `begin`: the unit of work belongs to the
   application layer (ADR-002, `txn-placement` gate), which is what makes "one use case = one atomic
   change" checkable.
2. **`add` is not `save`.** `add` is the *insert* path and refuses a duplicate (B-3) or a second active
   attempt (B-1); `save` is the update path. Collapsing them would move the invariant into an upsert
   where nobody reads it.

`find_active_for_invoice` exists so B-1 has one obvious call site instead of a scatter of
`WHERE status NOT IN (...)` predicates that drift apart.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.billing.domain.ids import AttemptId, InvoiceId
from src.billing.domain.invoice import Invoice
from src.billing.domain.payment_attempt import PaymentAttempt
from src.billing.domain.values import InvoiceHash
from src.shared.domain.repository import Repository

__all__ = ["InvoiceRepository", "PaymentAttemptRepository"]


class InvoiceRepository(Repository[InvoiceId, Invoice], ABC):
    """Persistence port for the Invoice aggregate root."""

    @abstractmethod
    async def add(self, invoice: Invoice) -> None:
        """Insert a new invoice.

        Raises:
            DuplicateInvoice: an invoice with this hash already exists (B-3).
        """
        raise NotImplementedError("B-3 — see module doc")

    @abstractmethod
    async def find_by_id(self, id_: InvoiceId) -> Invoice | None:
        """Return the invoice or None. Never raises for absence."""
        raise NotImplementedError("B-3 — see module doc")

    @abstractmethod
    async def find_by_hash(self, hash_: InvoiceHash) -> Invoice | None:
        """The duplicate lookup for B-3; read-through, no cache."""
        raise NotImplementedError("B-3 — see module doc")

    @abstractmethod
    async def save(self, invoice: Invoice) -> None:
        """Update the invoice inside the caller's unit of work. No commit here."""
        raise NotImplementedError("B-2 — see module doc")


class PaymentAttemptRepository(Repository[AttemptId, PaymentAttempt], ABC):
    """Persistence port for the PaymentAttempt aggregate root."""

    @abstractmethod
    async def add(self, attempt: PaymentAttempt) -> None:
        """Insert a new attempt.

        Raises:
            InvoiceNotPayable: the invoice already has a non-terminal attempt (B-1).
        """
        raise NotImplementedError("B-1 — see module doc")

    @abstractmethod
    async def find_by_id(self, id_: AttemptId) -> PaymentAttempt | None:
        raise NotImplementedError("B-7 — see module doc")

    @abstractmethod
    async def find_active_for_invoice(self, invoice_id: InvoiceId) -> PaymentAttempt | None:
        """The single non-terminal attempt for an invoice, or None (B-1)."""
        raise NotImplementedError("B-1 — see module doc")
