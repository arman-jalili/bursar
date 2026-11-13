"""The 12 domain events of the Mandate context — frozen payload schemas (v1).

Canonical: .pi/architecture/modules/mandate.md#domain-events
Reference: .pi/architecture/decisions/ADR-003-cross-context-communication.md

Payloads are part of the frozen contract because they are sealed into evidence envelopes
(ADR-007) and consumed by Authority at dispatch. Renaming a field changes the sealed bytes of
historical facts — so a payload change is a contract version bump, not a refactor.

Every event here passes ADR-008 triage: a domain expert cares, and/or it crosses a boundary, and/or
it needs an audit trail. `event_name` is the wire name: stable, past tense, and matching the
module doc table exactly.

Subscribers: Authority (all of them — it must invalidate any plan-time view), Evidence (seal),
Console (read models). No event carries routing details: `BankDigest` is already a digest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from src.shared.domain.event import DomainEvent

__all__ = [
    "AgentAuthorised",
    "CapChanged",
    "ConstitutionVersionPublished",
    "MandateCreated",
    "OwnerRegistered",
    "PayeeDigestChanged",
    "PayeeFrozen",
    "PayeeQuarantined",
    "PayeeReapproved",
    "PayeeRegistered",
    "PayerEnrolled",
    "ThresholdChanged",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class MandateCreated(DomainEvent):
    """A household mandate exists with owner, payer, agent and constitution v1 (FR-001)."""

    event_name: ClassVar[str] = "MandateCreated"

    household_id: str = ""
    owner_id: str = ""
    payer_id: str = ""
    agent_id: str = ""
    constitution_version: int = 1


@dataclass(frozen=True, slots=True, kw_only=True)
class OwnerRegistered(DomainEvent):
    """The owner address is the sole signature authority (FR-001, H-5)."""

    event_name: ClassVar[str] = "OwnerRegistered"

    household_id: str = ""
    owner_id: str = ""
    address: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class PayerEnrolled(DomainEvent):
    """The parent is enrolled as beneficiary; no signing capability is granted (H-2)."""

    event_name: ClassVar[str] = "PayerEnrolled"

    household_id: str = ""
    payer_id: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentAuthorised(DomainEvent):
    """A software identity is granted proposal-only authority (H-2, FR-009)."""

    event_name: ClassVar[str] = "AgentAuthorised"

    household_id: str = ""
    agent_id: str = ""
    constitution_version: int = 1


@dataclass(frozen=True, slots=True, kw_only=True)
class ConstitutionVersionPublished(DomainEvent):
    """A new immutable rule set is in force; the previous one is superseded (FR-002, H-4, H-7)."""

    event_name: ClassVar[str] = "ConstitutionVersionPublished"

    constitution_id: str = ""
    version: int = 0
    content_hash: str = ""
    cap_micro_usdc: int = 0
    threshold_micro_usdc: int = 0
    published_at_iso: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class CapChanged(DomainEvent):
    """The daily ceiling changed; in-flight reservations stay on their own version (H-7)."""

    event_name: ClassVar[str] = "CapChanged"

    household_id: str = ""
    version: int = 0
    from_micro_usdc: int = 0
    to_micro_usdc: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class ThresholdChanged(DomainEvent):
    """The auto-pay limit changed, shifting which future payments escalate (FR-014)."""

    event_name: ClassVar[str] = "ThresholdChanged"

    household_id: str = ""
    version: int = 0
    from_micro_usdc: int = 0
    to_micro_usdc: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class PayeeRegistered(DomainEvent):
    """A payee entered the allowlist as `NEW`, with a verified digest (FR-004, P-1)."""

    event_name: ClassVar[str] = "PayeeRegistered"

    payee_id: str = ""
    name: str = ""
    address: str = ""
    digest: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class PayeeDigestChanged(DomainEvent):
    """An invoice presented routing details unlike the verified digest (FR-005, P-2)."""

    event_name: ClassVar[str] = "PayeeDigestChanged"

    payee_id: str = ""
    presented_digest: str = ""
    verified_digest: str = ""
    invoice_id: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class PayeeQuarantined(DomainEvent):
    """Payee is ineligible until the owner re-approves (FR-005, P-2, P-3).

    The address is deliberately unchanged — the money is not redirected, it is stopped.
    """

    event_name: ClassVar[str] = "PayeeQuarantined"

    payee_id: str = ""
    reason: str = "bank_digest_mismatch"
    at_iso: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class PayeeFrozen(DomainEvent):
    """Owner suspended the payee entirely; strictly stronger than quarantine (FR-006, P-4)."""

    event_name: ClassVar[str] = "PayeeFrozen"

    payee_id: str = ""
    actor_id: str = ""
    at_iso: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class PayeeReapproved(DomainEvent):
    """Owner accepted new bank details; the digest baseline is replaced (FR-005, P-5)."""

    event_name: ClassVar[str] = "PayeeReapproved"

    payee_id: str = ""
    previous_digest: str = ""
    new_digest: str = ""
    actor_id: str = ""
