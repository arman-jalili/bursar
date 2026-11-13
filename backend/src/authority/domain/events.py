"""The twelve Authority domain events — frozen payload schemas (v1).

Canonical: .pi/architecture/modules/authority.md#domain-events
Reference: docs/contracts/authority-contract-freeze.md §2.8

Payloads are part of the frozen contract because Evidence seals them (ADR-007) and Settlement and
Console consume them. Renaming a field changes the sealed bytes of a historical fact, so a payload
change is a contract version bump, not a refactor.

Exactly twelve events exist — the module doc table is the whole list, and ADR-008 triage forbids
inventing a thirteenth. `event_name` is the wire name: stable, past tense, and matching that table.

Three naming decisions worth stating, because they are contracts rather than style:

* Amounts are integer **micro-USDC** (`amount_micro_usdc`, `committed_micro_usdc`,
  `reserved_micro_usdc`, `headroom_micro_usdc`) — ADR-002. The module doc's table abbreviates them
  as `amount_usdc`; the unit is the contract, so the field name says it.
* Timestamps are **ISO-8601 strings with an explicit offset** (`read_at_iso`, `refused_at_iso`, …).
  A naive datetime on the wire is a bug in an audit trail, and a string keeps the sealed bytes
  independent of the consumer's datetime library.
* The expiry event is class `ApprovalExpiredEvent` with wire name ``"ApprovalExpired"``, because
  `domain/errors.py` already owns `ApprovalExpired` for the refusal. Subscribers and evidence key on
  the wire name, which is unchanged.

`PaymentIntentIssued` is the one event that carries `payee_address` and `bank_digest`. That is not a
relaxation of the ACL (A-2): the fields are copied from Mandate's verified record when the intent is
issued, never from the proposal, and Settlement cannot dispatch from an event that omits the
destination. Provenance is the guarantee here — the address is present *because* Mandate supplied it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from src.shared.domain.event import DomainEvent

__all__ = [
    "ApprovalExpiredEvent",
    "ApprovalGranted",
    "ApprovalRejected",
    "ApprovalRequested",
    "AuthorityDetermined",
    "CapacityCommitted",
    "CapacityRefused",
    "CapacityReleased",
    "CapacityReserved",
    "PaymentAllowed",
    "PaymentIntentIssued",
    "PaymentRefused",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class PaymentIntentIssued(DomainEvent):
    """The code-constructed intent with the exact fields to be signed (A-1 … A-4)."""

    event_name: ClassVar[str] = "PaymentIntentIssued"

    intent_id: str = ""
    invoice_id: str = ""
    payee_id: str = ""
    #: Mandate's verified address — never the proposal's (A-2).
    payee_address: str = ""
    amount_micro_usdc: int = 0
    #: Mandate's verified digest — never the invoice's (A-2).
    bank_digest: str = ""
    is_new_payee: bool = False
    requires_owner_signature: bool = False
    constitution_version: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthorityDetermined(DomainEvent):
    """The verdict plus the rules consulted in the same read (A-5 … A-7)."""

    event_name: ClassVar[str] = "AuthorityDetermined"

    determination_id: str = ""
    intent_id: str = ""
    #: `allow` | `deny` | `escalate` — the closed verdict set.
    verdict: str = ""
    #: Closed `DenialReason` values, lowercase on the wire; non-empty for a deny (A-5).
    reason_codes: tuple[str, ...] = ()
    constitution_version: int = 0
    payee_status: str = ""
    read_at_iso: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class PaymentAllowed(DomainEvent):
    """The only event that authorises dispatch (A-8).

    `ESCALATE` does not publish this event: escalation publishes `ApprovalRequested`, and
    `PaymentAllowed` follows only after the owner signature is verified.
    """

    event_name: ClassVar[str] = "PaymentAllowed"

    intent_id: str = ""
    amount_micro_usdc: int = 0
    reservation_id: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class PaymentRefused(DomainEvent):
    """A refusal is a fact like any other, and it must produce evidence (A-8)."""

    event_name: ClassVar[str] = "PaymentRefused"

    intent_id: str = ""
    reason_codes: tuple[str, ...] = ()
    refused_at_iso: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class CapacityReserved(DomainEvent):
    """Amount held against the daily cap by one atomic conditional update (A-9)."""

    event_name: ClassVar[str] = "CapacityReserved"

    day: str = ""
    reservation_id: str = ""
    intent_id: str = ""
    amount_micro_usdc: int = 0
    committed_micro_usdc: int = 0
    reserved_micro_usdc: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class CapacityRefused(DomainEvent):
    """Headroom was insufficient; nothing was reserved (A-9)."""

    event_name: ClassVar[str] = "CapacityRefused"

    day: str = ""
    intent_id: str = ""
    amount_micro_usdc: int = 0
    headroom_micro_usdc: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class ApprovalRequested(DomainEvent):
    """An escalation opened a signature request bound to one exact intent (A-13)."""

    event_name: ClassVar[str] = "ApprovalRequested"

    approval_id: str = ""
    intent_id: str = ""
    typed_data_hash: str = ""
    expires_at_iso: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class ApprovalGranted(DomainEvent):
    """The owner signature verified against the bound intent and the mandate owner (A-13, A-15)."""

    event_name: ClassVar[str] = "ApprovalGranted"

    approval_id: str = ""
    intent_id: str = ""
    signer: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class ApprovalRejected(DomainEvent):
    """Invalid signature, wrong signer, or binding mismatch; no dispatch followed (A-13, A-15)."""

    event_name: ClassVar[str] = "ApprovalRejected"

    approval_id: str = ""
    intent_id: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class ApprovalExpiredEvent(DomainEvent):
    """The signature window closed; the owner must sign a fresh intent (A-14).

    The class name carries the `Event` suffix only because the refusal in `domain/errors.py` already
    owns `ApprovalExpired`. The wire name — what subscribers and evidence use — is `ApprovalExpired`.
    """

    event_name: ClassVar[str] = "ApprovalExpired"

    approval_id: str = ""
    intent_id: str = ""
    expired_at_iso: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class CapacityCommitted(DomainEvent):
    """A reservation became committed spend after settlement confirmed (A-10, A-11)."""

    event_name: ClassVar[str] = "CapacityCommitted"

    day: str = ""
    reservation_id: str = ""
    intent_id: str = ""
    amount_micro_usdc: int = 0
    committed_micro_usdc: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class CapacityReleased(DomainEvent):
    """A reservation was released because the payment provably did not happen (A-10)."""

    event_name: ClassVar[str] = "CapacityReleased"

    day: str = ""
    reservation_id: str = ""
    intent_id: str = ""
    amount_micro_usdc: int = 0
    reason: str = ""
