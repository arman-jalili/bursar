"""Authority commands and results (frozen).

Canonical: .pi/architecture/modules/authority.md#application-services
Reference: docs/contracts/authority-contract-freeze.md §2

Decisions encoded in the shapes:

* **No command carries a payee address, a digest or a cap.** They carry ids and an optional claimed
  amount. A field that does not exist cannot be injected (A-2, A-3).
* **Amounts are integer micro-units** via `Money` (ADR-002); the DTOs use plain ints so the transport does
  not have to import the domain.
* **`DeterminationView` exposes `reason_codes` as strings**, because the console translates them and
  Evidence seals them — a domain enum in a DTO would leak Authority's vocabulary into both.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

__all__ = [
    "DeterminationView",
    "EscalateForSignatureCommand",
    "EscalateForSignatureResult",
    "EvaluateAuthorityCommand",
    "EvaluateAuthorityResult",
    "IntentView",
    "ReconcileReservationCommand",
    "ReconcileReservationResult",
    "ReserveCapacityCommand",
    "ReserveCapacityResult",
    "SubmitOwnerSignatureCommand",
    "SubmitOwnerSignatureResult",
]


@dataclass(frozen=True, slots=True)
class IntentView:
    """An intent as the API exposes it. The exact fields the owner is asked to sign (A-13)."""

    intent_id: str
    invoice_id: str
    payee_id: str
    payee_address: str
    amount_micro_usdc: int
    bank_digest: str
    is_new_payee: bool
    requires_owner_signature: bool
    constitution_version: int


@dataclass(frozen=True, slots=True)
class DeterminationView:
    """The verdict plus the rules it consulted (A-5, A-6)."""

    determination_id: str
    intent_id: str
    verdict: str
    reason_codes: tuple[str, ...] = ()
    constitution_version: int = 0
    payee_status: str = ""
    read_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class EvaluateAuthorityCommand:
    """The evaluation request. Only ids and a *claimed* amount — the invoice is the source of truth (A-3)."""

    attempt_id: str
    household_id: str
    claimed_amount_micro_usdc: int | None = None


@dataclass(frozen=True, slots=True)
class EvaluateAuthorityResult:
    intent: IntentView
    determination: DeterminationView
    events: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReserveCapacityCommand:
    intent_id: str
    amount_micro_usdc: int
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ReserveCapacityResult:
    reservation_id: str
    day: str
    reserved_micro_usdc: int
    headroom_micro_usdc: int
    events: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EscalateForSignatureCommand:
    determination_id: str
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class EscalateForSignatureResult:
    approval_id: str
    intent_id: str
    typed_data_hash: str
    expires_at: datetime | None = None
    events: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SubmitOwnerSignatureCommand:
    approval_id: str
    signature_hex: str


@dataclass(frozen=True, slots=True)
class SubmitOwnerSignatureResult:
    approval_id: str
    granted: bool
    events: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class RejectApprovalCommand:
    approval_id: str


@dataclass(frozen=True, slots=True)
class RejectApprovalResult:
    approval_id: str
    intent_id: str
    rejected: bool = True
    events: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ReconcileReservationCommand:
    reservation_id: str
    outcome: str  # "confirmed" | "reverted"


@dataclass(frozen=True, slots=True)
class ReconcileReservationResult:
    reservation_id: str
    ledger_committed_micro_usdc: int
    ledger_reserved_micro_usdc: int
    events: tuple[str, ...] = ()
