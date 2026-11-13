"""Billing commands and results (frozen) — the shape every caller codes against.

Canonical: .pi/architecture/modules/billing.md#application-services
Reference: docs/contracts/billing-contract-freeze.md §2.7

Two decisions encoded here:

* **`ProposePaymentCommand` carries an `invoice_id` and an optional `proposed_amount_micro_usdc` — and
  nothing else.** There is no field for a payee address, a command path or a cap, so a proposal cannot
  smuggle one through the transport: the type is the first line of B-5.
* Amounts are integer micro-units (ADR-002); digests are hex strings. Routing details never appear in a
  DTO — `RecordInvoiceCommand` takes them once, and the service hashes them immediately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

__all__ = [
    "AttemptView",
    "InvoiceView",
    "ProposePaymentCommand",
    "ProposePaymentResult",
    "RecordInvoiceCommand",
    "RecordInvoiceResult",
]


@dataclass(frozen=True, slots=True)
class InvoiceView:
    """An invoice as the API exposes it. Digest only — never routing details."""

    invoice_id: str
    payee_id: str
    invoice_hash: str
    amount_micro_usdc: int
    due_date_iso: str
    presented_digest: str
    status: str


@dataclass(frozen=True, slots=True)
class AttemptView:
    attempt_id: str
    invoice_id: str
    status: str


@dataclass(frozen=True, slots=True)
class RecordInvoiceCommand:
    """Register one bill (FR-007)."""

    payee_id: str
    amount_micro_usdc: int
    due_date: date
    #: Normalized document used for the hash — the identity of the bill (B-3).
    document: dict[str, object] = field(default_factory=dict)
    #: Digest of the routing details as printed on the invoice. Compared by Mandate; never routed to
    #: (B-4).
    presented_digest: str = ""


@dataclass(frozen=True, slots=True)
class RecordInvoiceResult:
    invoice: InvoiceView
    duplicate: bool = False
    events: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProposePaymentCommand:
    """The agent's whole vocabulary: which invoice, and (optionally) what it believes is owed."""

    invoice_id: str
    proposed_amount_micro_usdc: int | None = None


@dataclass(frozen=True, slots=True)
class ProposePaymentResult:
    attempt: AttemptView
    events: tuple[str, ...] = ()
