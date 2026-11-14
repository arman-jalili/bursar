"""The five catalog application services (frozen, FR-011 … FR-017).

Canonical: docs/architecture/modules/authority.md#application-services
Reference: docs/contracts/authority-contract-freeze.md §2

Each `execute` is one unit of work. The refusal cases listed in the docstrings are the contract: they are
what Phase B must raise, and what the behaviour tests assert.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.authority.application.dto import (
    EscalateForSignatureCommand,
    EscalateForSignatureResult,
    EvaluateAuthorityCommand,
    EvaluateAuthorityResult,
    ReconcileReservationCommand,
    ReconcileReservationResult,
    RejectApprovalCommand,
    RejectApprovalResult,
    ReserveCapacityCommand,
    ReserveCapacityResult,
    SubmitOwnerSignatureCommand,
    SubmitOwnerSignatureResult,
)

__all__ = [
    "EscalateForSignature",
    "EvaluateAuthority",
    "ReconcileReservation",
    "RejectApproval",
    "ReserveCapacity",
    "SubmitOwnerSignature",
]


class EvaluateAuthority(ABC):
    """Build the intent, re-read Mandate, decide, reserve (FR-011)."""

    @abstractmethod
    async def execute(self, command: EvaluateAuthorityCommand) -> EvaluateAuthorityResult:
        """Produce the intent and its determination.

        Raises:
            AuthorityRefusal: the attempt amount differs from the invoice (A-3).
            CapExceeded: the decision is ALLOW and the cap has no headroom (A-9).
        """
        raise NotImplementedError("A-5 — see module doc")


class ReserveCapacity(ABC):
    """The atomic hold against the daily cap (FR-013)."""

    @abstractmethod
    async def execute(self, command: ReserveCapacityCommand) -> ReserveCapacityResult:
        """Reserve, or refuse.

        Raises:
            CapExceeded: `committed + reserved + amount > cap` (A-9) — nothing is reserved.
        """
        raise NotImplementedError("A-9 — see module doc")


class EscalateForSignature(ABC):
    """Bind a signature request to one exact intent (FR-014)."""

    @abstractmethod
    async def execute(self, command: EscalateForSignatureCommand) -> EscalateForSignatureResult:
        """Open the approval.

        Raises:
            AuthorityRefusal: the determination is not an escalation (nothing to sign).
        """
        raise NotImplementedError("A-13 — see module doc")


class SubmitOwnerSignature(ABC):
    """Verify the owner's signature against the bound intent (FR-015)."""

    @abstractmethod
    async def execute(self, command: SubmitOwnerSignatureCommand) -> SubmitOwnerSignatureResult:
        """Grant or refuse, without side effect on refusal.

        Raises:
            ApprovalBindingMismatch: the signature covers a different intent (A-13).
            ApprovalSingleUse: already consumed (A-14).
            ApprovalExpired: the window closed (A-14).
        """
        raise NotImplementedError("A-13 — see module doc")


class RejectApproval(ABC):
    """The owner declines a pending signature request (FR-015, A-14)."""

    @abstractmethod
    async def execute(self, command: RejectApprovalCommand) -> RejectApprovalResult:
        """Close the request without a signature; nothing is dispatched.

        Raises:
            NotFoundError: no approval with that id.
            ApprovalSingleUse: already consumed (signed or declined).
            ApprovalBindingMismatch: already signed — a granted approval cannot be undone.
        """
        raise NotImplementedError("A-14 — see module doc")


class ReconcileReservation(ABC):
    """Commit or release against the settlement outcome (FR-017)."""

    @abstractmethod
    async def execute(self, command: ReconcileReservationCommand) -> ReconcileReservationResult:
        """Resolve the reservation exactly once.

        Raises:
            ReservationAlreadyResolved: the reservation was already resolved (A-10).
        """
        raise NotImplementedError("A-10 — see module doc")
