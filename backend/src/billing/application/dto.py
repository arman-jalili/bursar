"""Billing commands and results (frozen) — the shape every caller codes against.

Canonical: docs/architecture/modules/billing.md#application-services
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
    "ApplyDeterminationCommand",
    "ApplyDeterminationResult",
    "AttemptView",
    "InvoiceView",
    "ProposePaymentCommand",
    "ProposePaymentResult",
    "RecordInvoiceCommand",
    "RecordInvoiceResult",
    "SettleInvoiceCommand",
    "SettleInvoiceResult",
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


@dataclass(frozen=True, slots=True)
class SettleInvoiceCommand:
    """Inbound `SettlementConfirmed` → close the invoice (ADR-003, module doc sequence 7).

    `event_id` is the publisher's delivery identity: at-least-once delivery means the same settlement
    can arrive twice, and the subscriber must make the replay a no-op. The state check (a settled
    invoice refuses a second settlement) is the dedupe; the field is carried so a durable
    `(event_id, handler)` table can be added without changing the command.
    """

    invoice_id: str
    tx_hash: str
    event_id: str = ""


@dataclass(frozen=True, slots=True)
class SettleInvoiceResult:
    invoice: InvoiceView
    duplicate: bool = False
    events: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ApplyDeterminationCommand:
    """Inbound Authority determination applied to one attempt (B-7).

    Billing does not decide `determination`; it records what Authority decided. An allow/escalate
    verdict dispatches; anything else refuses and frees the invoice.
    """

    attempt_id: str
    determination: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ApplyDeterminationResult:
    attempt: AttemptView
    invoice: InvoiceView | None = None
    events: tuple[str, ...] = ()
