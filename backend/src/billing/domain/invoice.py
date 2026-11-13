"""Invoice — the bill document, and the invoice-level invariants (frozen).

Canonical: .pi/architecture/modules/billing.md#components-invoice
Reference: docs/contracts/billing-contract-freeze.md (B-1 … B-4)

    B-1  at most one non-terminal payment attempt at a time
    B-2  a settled invoice is closed forever
    B-3  the hash identifies the bill; a second identical hash is the same invoice
    B-4  `presented_digest` is stored for comparison only — never used for routing

`mark_settled` is the *only* transition that closes an invoice, and it refuses to run twice. There is no
setter and no `update()`: `status` moves through intention methods so the invariants stay enforceable.

Why the presented digest is stored at all: Mandate compares it against the payee's verified baseline
(scenario 2). Billing must carry the fact without ever treating it as a destination — the address comes
from Mandate, never from the document.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from src.shared.domain.aggregate import AggregateRoot

from src.billing.domain.ids import InvoiceId, PayeeId
from src.billing.domain.values import BilledAmount, InvoiceHash, InvoiceStatus
from src.mandate.domain.values import BankDigest

__all__ = ["Invoice"]


@dataclass(eq=False)
class Invoice(AggregateRoot):
    """A bill presented for payment. Identity persists; `status` only moves forward."""

    id: InvoiceId
    payee_id: PayeeId
    hash: InvoiceHash
    amount: BilledAmount
    due_date: date
    presented_digest: BankDigest
    status: InvoiceStatus

    @classmethod
    def record(
        cls,
        *,
        payee_id: PayeeId,
        amount: BilledAmount,
        due_date: date,
        document: Mapping[str, object],
        presented_digest: BankDigest,
        existing_hashes: Sequence[InvoiceHash] = (),
    ) -> Invoice:
        """Record a bill, refusing a hash that is already known (B-3).

        `existing_hashes` is passed in rather than looked up: the aggregate must be constructible in a
        unit test without a database, and the *rule* (same hash = same bill) is domain knowledge, not a
        storage accident.

        Raises:
            DuplicateInvoice: the hash matches a known invoice (B-3).
        """
        raise NotImplementedError("B-3 — see module doc")

    def can_accept_attempt(self) -> bool:
        """True when a new attempt may be created (B-1, B-2).

        False while an attempt is in flight, and False forever once settled.
        """
        raise NotImplementedError("B-1 — see module doc")

    def is_duplicate_of(self, other: InvoiceHash) -> bool:
        """True when `other` identifies this same bill (B-3)."""
        raise NotImplementedError("B-3 — see module doc")

    def mark_settled(self) -> None:
        """Close the invoice after a confirmed settlement (B-2).

        Raises:
            InvoiceAlreadySettled: called twice — a settlement is final, so a second call is a bug, not
                an idempotent no-op. Silently accepting it would let a replayed settlement look normal.
        """
        raise NotImplementedError("B-2 — see module doc")
