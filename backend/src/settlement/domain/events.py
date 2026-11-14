"""The seven Settlement domain events — frozen payload schemas (v1).

Canonical: docs/architecture/modules/settlement.md#domain-events
Reference: docs/contracts/settlement-contract-freeze.md §2.12

Payloads are part of the frozen contract because they are sealed into evidence envelopes (ADR-007) and
consumed by Authority (commit or release) and Evidence (envelope the outcome). Renaming a field changes
the sealed bytes of a historical fact, so a payload change is a contract version bump, not a refactor.

Exactly seven events exist — the Modeling Depth Note (ADR-008) forbids inventing an eighth. Each passes
the triage: a domain expert cares, and/or it crosses a boundary, and/or it needs an audit trail.

Three naming decisions worth stating:

* Amounts are integer **micro-USDC** (`amount_micro_usdc`), matching ADR-002 and every DTO. The module
  doc's table says `amount_usdc`; the unit is the contract, so the field name says it.
* The refused-replay event is class `DuplicateSettlementBlockedEvent` with wire name
  ``"DuplicateSettlementBlocked"``. The class name differs only because `domain/errors.py` already owns
  `DuplicateSettlementBlocked` for the refusal itself; the wire name — what subscribers and evidence
  key on — is unchanged.
* `occurred_at` replaces the table's `detected_at`: every `DomainEvent` already carries the instant, and
  a second timestamp field would let a payload disagree with its envelope.

Events carry no routing details, ever. `payee_address` is absent on purpose: the address is on the
order, and an event stream that re-publishes it invites a subscriber to route from an event.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from src.shared.domain.event import DomainEvent

__all__ = [
    "DuplicateSettlementBlockedEvent",
    "NullifierSpent",
    "ReceiptAnchored",
    "SettlementConfirmed",
    "SettlementOrdered",
    "SettlementReverted",
    "SettlementSubmitted",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class SettlementOrdered(DomainEvent):
    """An allowed intent became an executable order with its nullifier (SC-1, SC-5)."""

    event_name: ClassVar[str] = "SettlementOrdered"

    order_id: str = ""
    intent_id: str = ""
    invoice_id: str = ""
    nullifier: str = ""
    amount_micro_usdc: int = 0
    chain_id: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class SettlementSubmitted(DomainEvent):
    """A tx hash was persisted before broadcast (SC-3). Internal: does not cross the boundary."""

    event_name: ClassVar[str] = "SettlementSubmitted"

    order_id: str = ""
    tx_hash: str = ""
    #: The account nonce the transaction used — the audit trail for "no second nonce".
    nonce: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class SettlementConfirmed(DomainEvent):
    """The receipt reached required confirmations — the only event that commits the cap (SC-7)."""

    event_name: ClassVar[str] = "SettlementConfirmed"

    order_id: str = ""
    intent_id: str = ""
    tx_hash: str = ""
    block_number: int = 0
    confirmations: int = 0
    amount_micro_usdc: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class SettlementReverted(DomainEvent):
    """The contract rejected the transaction. A refusal, terminal, exactly once per order (SC-6, SC-8)."""

    event_name: ClassVar[str] = "SettlementReverted"

    order_id: str = ""
    intent_id: str = ""
    tx_hash: str = ""
    revert_reason: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class DuplicateSettlementBlockedEvent(DomainEvent):
    """A nullifier was already spent, locally or on-chain; nothing moved (SC-5, SC-6).

    Wire name stays ``"DuplicateSettlementBlocked"`` — the class suffix exists only to avoid shadowing
    the refusal of the same name.
    """

    event_name: ClassVar[str] = "DuplicateSettlementBlocked"

    intent_id: str = ""
    invoice_id: str = ""
    nullifier: str = ""
    #: "local" or "on_chain" — which lock refused first. Never used to decide a retry.
    detected_by: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class NullifierSpent(DomainEvent):
    """The invoice's once-only marker is consumed for this scope (SC-5). Internal audit fact."""

    event_name: ClassVar[str] = "NullifierSpent"

    nullifier: str = ""
    order_id: str = ""
    invoice_id: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class ReceiptAnchored(DomainEvent):
    """An evidence/envelope hash was written on-chain (ADR-006).

    Anchoring is a chain write with its own receipt and its own cost, so it is a settlement fact — but
    `is_anchor` keeps it out of payment conclusions (SC-7, SC-10).
    """

    event_name: ClassVar[str] = "ReceiptAnchored"

    anchor_tx: str = ""
    anchored_hash: str = ""
    order_id: str = ""
