"""Invoice — the bill document, and the invoice-level invariants (frozen).

Canonical: docs/architecture/modules/billing.md#components-invoice
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
from dataclasses import dataclass, field
from datetime import date

from src.billing.domain.errors import DuplicateInvoice, InvoiceAlreadySettled
from src.billing.domain.events import InvoiceRecorded, InvoiceSettled
from src.billing.domain.ids import InvoiceId, PayeeId, new_id
from src.billing.domain.values import BilledAmount, InvoiceHash, InvoiceStatus
from src.mandate.domain.values import BankDigest
from src.shared.domain.aggregate import AggregateRoot

__all__ = ["Invoice"]

#: Statuses in which a new attempt may be created (B-1, B-2). `IN_FLIGHT` is deliberately absent.
_PAYABLE_STATUSES = frozenset({InvoiceStatus.RECEIVED, InvoiceStatus.OUTSTANDING})


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

    #: The attempt currently holding the invoice, if any. In-memory guard for B-1; persistence mirrors
    #: it with status `IN_FLIGHT` + a partial unique index.
    _active_attempt: object | None = field(default=None, init=False, repr=False, compare=False)

    @classmethod
    def from_document(
        cls,
        *,
        payee_id: PayeeId,
        amount: BilledAmount,
        due_date: date,
        document: Mapping[str, object],
        presented_digest: BankDigest,
        existing_hashes: Sequence[InvoiceHash] = (),
    ) -> Invoice:
        """Build an invoice from a bill document, refusing a known hash (B-3).

        Named `from_document` — **not** `record`. `AggregateRoot.record(self, event)` is the event recorder:
        a classmethod with the same name shadowed it, so `invoice.record(InvoiceRecorded(...))` would have
        called the factory instead of recording a fact, and mypy caught the override. Naming the factory
        after its input also matches `InvoiceHash.from_document`.

        `existing_hashes` is passed in rather than looked up: the aggregate must be constructible in a
        unit test without a database, and the *rule* (same hash = same bill) is domain knowledge, not a
        storage accident.

        Raises:
            DuplicateInvoice: the hash matches a known invoice (B-3).
        """
        invoice_hash = InvoiceHash.from_document(document)
        for known in existing_hashes:
            if invoice_hash.same_as(known):
                raise DuplicateInvoice(invoice_hash=invoice_hash.value)

        invoice = cls(
            id=InvoiceId(new_id()),
            payee_id=payee_id,
            hash=invoice_hash,
            amount=amount,
            due_date=due_date,
            presented_digest=presented_digest,
            status=InvoiceStatus.RECEIVED,
        )
        invoice.record(
            InvoiceRecorded(
                invoice_id=str(invoice.id),
                payee_id=str(payee_id),
                invoice_hash=invoice_hash.value,
                amount_micro_usdc=amount.micro_usdc,
                due_date_iso=due_date.isoformat(),
                presented_digest=presented_digest.hash,
            )
        )
        return invoice

    def can_accept_attempt(self) -> bool:
        """True when a new attempt may be created (B-1, B-2).

        False while an attempt is in flight, and False forever once settled.
        """
        return self.status in _PAYABLE_STATUSES

    def is_duplicate_of(self, other: InvoiceHash) -> bool:
        """True when `other` identifies this same bill (B-3)."""
        return self.hash.same_as(other)

    def mark_settled(self) -> None:
        """Close the invoice after a confirmed settlement (B-2).

        Raises:
            InvoiceAlreadySettled: called twice — a settlement is final, so a second call is a bug, not
                an idempotent no-op. Silently accepting it would let a replayed settlement look normal.
        """
        if self.status is InvoiceStatus.SETTLED:
            raise InvoiceAlreadySettled(str(self.id))
        self.status = InvoiceStatus.SETTLED
        self._active_attempt = None
        self.record(
            InvoiceSettled(
                invoice_id=str(self.id),
                invoice_hash=self.hash.value,
                tx_hash="",
            )
        )
