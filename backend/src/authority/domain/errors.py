"""Authority refusal vocabulary (frozen).

Canonical: .pi/architecture/modules/authority.md#components
Reference: docs/contracts/authority-contract-freeze.md §3

Every refusal extends the shared `RefusalError`, so a refusal is a documented `409` with a domain code
(ADR-004) — never a `500`, and never a silently ignored return value. Each class exists because one
invariant needs it named:

    CapExceeded                 A-9      committed + reserved + amount > cap
    ReservationAlreadyResolved  A-10     a reservation resolved twice
    DeterminationWithoutReason  A-5/A-7  a denial with no code, or a verdict with no version
    ApprovalBindingMismatch     A-13     the signature covers a different intent
    ApprovalSingleUse           A-14     this approval was already consumed
    ApprovalExpired             A-14     the signature window closed
    DispatchWithoutAuthority    A-8      dispatch attempted with no allow/escalate determination

Two details worth defending in the code, not just the docs:

* **`reason_code` uses the domain vocabulary (lowercase `DenialReason`)**, while `code` is the wire
  vocabulary (`ErrorCode`, upper case). The console translates the former; the envelope carries the latter.
  A test caught these drifting, which is why they are now sourced from their own closed sets.
* **Payloads are an explicit `details` mapping, never a `**kwargs` tail** — a splat could pass `retryable`
  or `code` and rewrite the refusal.
"""

from __future__ import annotations

from src.authority.domain.values import DenialReason
from src.shared.domain.errors import ErrorCode, RefusalError

__all__ = [
    "ApprovalBindingMismatch",
    "ApprovalExpired",
    "ApprovalSingleUse",
    "AuthorityRefusal",
    "CapExceeded",
    "DeterminationWithoutReason",
    "DispatchWithoutAuthority",
    "ReservationAlreadyResolved",
]


class AuthorityRefusal(RefusalError):
    """Base for every refusal this context raises."""

    reason_code: str = "authority_refused"


class CapExceeded(AuthorityRefusal):
    """A reservation would push `committed + reserved` above the daily cap (A-9)."""

    def __init__(
        self, needed_micro_usdc: int = 0, headroom_micro_usdc: int = 0, **extra: str
    ) -> None:
        super().__init__(
            ErrorCode.CAP_EXCEEDED,
            "The daily cap would be exceeded; nothing was reserved.",
            details={
                "needed_micro_usdc": str(needed_micro_usdc),
                "headroom_micro_usdc": str(headroom_micro_usdc),
                **extra,
            },
        )
        self.reason_code = DenialReason.CAP_EXCEEDED.value


class ReservationAlreadyResolved(AuthorityRefusal):
    """A reservation is committed or released exactly once (A-10)."""

    def __init__(self, reservation_id: str = "", status: str = "", **extra: str) -> None:
        super().__init__(
            ErrorCode.CONFLICT,
            "This reservation was already resolved.",
            details={"reservation_id": reservation_id, "status": status, **extra},
        )
        self.reason_code = "reservation_already_resolved"


class DeterminationWithoutReason(AuthorityRefusal):
    """A verdict with no code, or a determination with no constitution version (A-5, A-7)."""

    def __init__(self, detail: str = "", **extra: str) -> None:
        super().__init__(
            ErrorCode.VALIDATION_FAILED,
            "A determination must carry its reason codes and the constitution version it consulted.",
            details={"detail": detail, **extra},
        )
        self.reason_code = "determination_without_reason"


class ApprovalBindingMismatch(AuthorityRefusal):
    """The owner signature does not cover *this* intent (A-13)."""

    def __init__(self, field: str = "", **extra: str) -> None:
        super().__init__(
            ErrorCode.APPROVAL_INVALID,
            "The signature does not cover this exact payment.",
            details={"field": field, **extra},
        )
        self.reason_code = DenialReason.APPROVAL_INVALID.value


class ApprovalSingleUse(AuthorityRefusal):
    """The approval was already consumed; one signature cannot dispatch twice (A-14)."""

    def __init__(self, approval_id: str = "", **extra: str) -> None:
        super().__init__(
            ErrorCode.APPROVAL_INVALID,
            "This approval has already been used.",
            details={"approval_id": approval_id, **extra},
        )
        self.reason_code = DenialReason.APPROVAL_INVALID.value


class ApprovalExpired(AuthorityRefusal):
    """The signature window closed before dispatch (A-14); the owner must re-sign a fresh intent."""

    def __init__(self, approval_id: str = "", **extra: str) -> None:
        super().__init__(
            ErrorCode.APPROVAL_INVALID,
            "This approval has expired.",
            details={"approval_id": approval_id, **extra},
        )
        self.reason_code = DenialReason.APPROVAL_INVALID.value


class DispatchWithoutAuthority(AuthorityRefusal):
    """Dispatch was attempted without an allow/escalate determination (A-8)."""

    def __init__(self, verdict: str = "", **extra: str) -> None:
        super().__init__(
            ErrorCode.CONFLICT,
            "No determination permits this dispatch.",
            details={"verdict": verdict, **extra},
        )
        self.reason_code = "dispatch_without_authority"
