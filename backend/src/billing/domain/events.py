"""The seven Billing domain events — frozen payload schemas (v1).

Canonical: docs/architecture/modules/billing.md#domain-events
Reference: docs/contracts/billing-contract-freeze.md §2.8

Payloads are part of the frozen contract because they are sealed into evidence envelopes (ADR-007)
and consumed by Authority and Evidence. Renaming a field changes the sealed bytes of historical
facts, so a payload change is a contract version bump, not a refactor.

Exactly seven events exist — the Modeling Depth Note (ADR-008) forbids inventing an eighth. Each
passes the ADR-008 triage: a domain expert cares, and/or it crosses a boundary, and/or it needs an
audit trail. `event_name` is the wire name: stable, past tense, and matching the module doc table.

Two naming decisions worth stating:

* Amounts are integer **micro-USDC** (`amount_micro_usdc`), matching ADR-002 and every DTO. The
  module doc's event table says `amount_usdc`; the unit is the contract, so the field name says it.
* The rejected-proposal event is class `ProposalRejectedEvent` with wire name ``"ProposalRejected"``.
  The class name differs only because `domain/errors.py` already owns `ProposalRejected` for the
  refusal itself; the wire name — the thing subscribers and evidence care about — is unchanged.

Events carry no routing details, ever. `presented_digest` is a digest (B-4), and `payee_id` is
Mandate's reference; a raw account number or address on the wire would defeat the ACL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from src.shared.domain.event import DomainEvent

__all__ = [
    "AttemptDispatched",
    "AttemptRefused",
    "DuplicateInvoiceDetected",
    "InvoiceRecorded",
    "InvoiceSettled",
    "PaymentProposed",
    "ProposalRejectedEvent",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class InvoiceRecorded(DomainEvent):
    """A bill entered the system with hash, amount and presented digest (FR-007, B-3, B-4)."""

    event_name: ClassVar[str] = "InvoiceRecorded"

    invoice_id: str = ""
    payee_id: str = ""
    invoice_hash: str = ""
    amount_micro_usdc: int = 0
    due_date_iso: str = ""
    #: Digest as presented on the document — kept for comparison, never for routing (B-4).
    presented_digest: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class DuplicateInvoiceDetected(DomainEvent):
    """A known invoice hash arrived again; it is not new demand (B-3)."""

    event_name: ClassVar[str] = "DuplicateInvoiceDetected"

    #: The id of the invoice already on file — the one that wins.
    invoice_id: str = ""
    invoice_hash: str = ""
    #: The id the caller would have received had the bill been new (kept for the audit trail).
    original_invoice_id: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class PaymentProposed(DomainEvent):
    """The agent produced a structured attempt; the request Authority must judge (FR-009, B-5)."""

    event_name: ClassVar[str] = "PaymentProposed"

    attempt_id: str = ""
    invoice_id: str = ""
    payee_id: str = ""
    amount_micro_usdc: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class ProposalRejectedEvent(DomainEvent):
    """A proposal was malformed or carried forbidden fields; no determination was requested (B-5).

    Wire name stays ``ProposalRejected``: the exception and the event describe the same fact, and
    subscribers key on the wire name, not the Python class.
    """

    event_name: ClassVar[str] = "ProposalRejected"

    #: Empty when the rejection happened before an attempt id existed.
    attempt_id: str = ""
    offending_fields: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class AttemptDispatched(DomainEvent):
    """Attempt moved to dispatched after an allow determination (lifecycle only, B-7)."""

    event_name: ClassVar[str] = "AttemptDispatched"

    attempt_id: str = ""
    invoice_id: str = ""
    intent_id: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class InvoiceSettled(DomainEvent):
    """Invoice closed as paid; it cannot generate more attempts (B-2)."""

    event_name: ClassVar[str] = "InvoiceSettled"

    invoice_id: str = ""
    invoice_hash: str = ""
    tx_hash: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class AttemptRefused(DomainEvent):
    """Attempt ended refused; the invoice returns to outstanding with no reservation (B-7)."""

    event_name: ClassVar[str] = "AttemptRefused"

    attempt_id: str = ""
    invoice_id: str = ""
    reason_codes: tuple[str, ...] = ()
