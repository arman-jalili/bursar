"""The three Evidence domain events — frozen payload schemas (v1).

Canonical: docs/architecture/modules/evidence.md#domain-events
Reference: docs/contracts/evidence-contract-freeze.md §2.7

Payloads are part of the frozen contract because they are sealed into later envelopes and consumed by
the Console. Exactly three events exist — the Modeling Depth Note (ADR-008) forbids inventing a
fourth. `event_name` is the wire name: stable, past tense, and matching the module doc table.

Evidence publishes facts about *itself* (sealed, anchored, failed verification). It also seals
foreign facts; those payloads are owned by their publishers (Authority, Billing, Settlement, Mandate)
and are never redeclared here — two definitions of one fact drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from src.shared.domain.event import DomainEvent

__all__ = ["EnvelopeAnchored", "EnvelopeSealed", "EvidenceVerificationFailed"]


@dataclass(frozen=True, slots=True, kw_only=True)
class EnvelopeSealed(DomainEvent):
    """A domain fact was wrapped, signed and appended (E-2)."""

    event_name: ClassVar[str] = "EnvelopeSealed"

    envelope_id: str = ""
    event_type: str = ""
    subject_intent_id: str | None = None
    subject_invoice_id: str | None = None
    subject_payee_id: str | None = None
    envelope_hash: str = ""
    anchor_mode: str = "per_envelope"


@dataclass(frozen=True, slots=True, kw_only=True)
class EnvelopeAnchored(DomainEvent):
    """The envelope hash was written on-chain, fixing integrity and time (E-8)."""

    event_name: ClassVar[str] = "EnvelopeAnchored"

    envelope_id: str = ""
    envelope_hash: str = ""
    anchor_tx: str = ""
    block_number: int = 0
    chain_id: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class EvidenceVerificationFailed(DomainEvent):
    """Re-verification disagreed with the sealed envelope or its anchor (E-7, E-8)."""

    event_name: ClassVar[str] = "EvidenceVerificationFailed"

    envelope_id: str = ""
    result: str = ""
    failing_field: str = ""
