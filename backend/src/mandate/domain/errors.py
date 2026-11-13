"""Mandate errors — the refusal vocabulary of this context.

Canonical: .pi/architecture/modules/mandate.md#components
Reference: .pi/architecture/decisions/ADR-004-api-design.md

Frozen contract v1. Each error maps to a shared `ErrorCode` so it reaches the wire through the
ADR-004 envelope (e.g. `OwnerActionRequired` → 403 `FORBIDDEN`), and each one exists because a
specific invariant needs it:

    OwnerActionRequired    H-3 / P-1 / P-3 — a non-owner actor tried to change the rules
    OwnerProofInvalid      H-5 / P-1 / P-5 — the owner signature did not cover the change
    ThresholdExceedsCap    H-6             — threshold above the cap would make the cap useless
    ConstitutionCorrupted  H-4             — 0 or 2 versions in force
    PayeeNotEligible       P-2 / P-4       — a payment was attempted against a blocked payee
    PayeeAlreadyRegistered — a duplicate payee inside one household

Implementation items raise these; they do not invent new ones without bumping the contract.
"""

from __future__ import annotations

from collections.abc import Mapping

from src.shared.domain.errors import BursarError, ErrorCode

__all__ = [
    "ConstitutionCorrupted",
    "MandateError",
    "OwnerActionRequired",
    "OwnerProofInvalid",
    "PayeeAlreadyRegistered",
    "PayeeNotEligible",
    "ThresholdExceedsCap",
]


class MandateError(BursarError):
    """Base class for every refusal raised by the Mandate context.

    Two deliberate choices:

    * Semantic errors are expressed through `default_code` / `default_status` rather than by
      inheriting the shared `ValidationError`/`ForbiddenError`/`RefusalError` classes. Those override
      `__init__`, and mixing them produced a diamond that nested `details` one level too deep
      (caught by the `payee-reapprove` contract test). One `__init__`, one meaning.
    * `details` is an **explicit mapping**, not `**kwargs`. With a `**kwargs` tail a caller could
      pass `code=` in `details` and silently rewrite the wire code of an error; mypy flagged exactly
      that during the contract freeze. An error's code must not be overridable from its payload.
    """

    default_code: ErrorCode = ErrorCode.CONFLICT
    default_status: int = 409

    def __init__(
        self,
        message: str = "",
        *,
        details: Mapping[str, str] | None = None,
        code: ErrorCode | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(
            code=code or self.default_code,
            message=message,
            http_status=http_status or self.default_status,
            details=dict(details or {}),
        )


class InvalidValue(MandateError, ValueError):
    """A value object was handed something it cannot represent (bad address, negative cap, float).

    Raised at construction, so an invalid value object never exists — callers cannot accidentally
    build one and pass it along. Maps to 422: the request was malformed, not refused by policy.

    Also a `ValueError` on purpose: "invalid value" is what `ValueError` means, so generic callers
    (and pydantic validators) can catch it without importing the domain hierarchy.
    """

    default_code = ErrorCode.VALIDATION_FAILED
    default_status = 422


class OwnerActionRequired(MandateError):
    """A non-owner actor (typically the agent) attempted an owner-only operation.

    Invariants: H-3, P-1, P-3. Maps to HTTP **403** — the credentials were fine, the actor was not,
    which is a different conversation from "the request conflicted" (409).
    """

    default_code = ErrorCode.FORBIDDEN
    default_status = 403

    def __init__(self, role: str = "", message: str = "", **details: str) -> None:
        super().__init__(
            message or "Only the owner may change the mandate, its payees or its rules.",
            details={"role": role, **details},
        )


class OwnerProofInvalid(MandateError):
    """The owner signature did not cover this exact change (H-5, P-1, P-5)."""

    def __init__(self, message: str = "", **details: str) -> None:
        super().__init__(
            message or "The owner signature does not cover this change.",
            code=ErrorCode.APPROVAL_INVALID,
            details=details,
        )


class ThresholdExceedsCap(MandateError):
    """`threshold > cap` (H-6): the auto-pay limit may not exceed the daily ceiling."""

    def __init__(self, threshold_usdc: str = "", cap_usdc: str = "", **details: str) -> None:
        super().__init__(
            f"Threshold {threshold_usdc} exceeds the daily cap {cap_usdc}.",
            details={"threshold_usdc": threshold_usdc, "cap_usdc": cap_usdc, **details},
        )


class ConstitutionCorrupted(MandateError):
    """Exactly one constitution version must be in force (H-4); found 0 or 2+."""

    def __init__(self, in_force_count: int, **details: str) -> None:
        super().__init__(
            f"Expected exactly one constitution version in force, found {in_force_count}.",
            code=ErrorCode.INTERNAL,
            http_status=500,
            details={"in_force_count": str(in_force_count), **details},
        )


class PayeeNotEligible(MandateError):
    """A payment was attempted against a quarantined or frozen payee (P-2, P-4)."""

    def __init__(self, payee_id: str = "", status: str = "", **details: str) -> None:
        super().__init__(
            f"Payee {payee_id} is not eligible (status {status}).",
            details={"payee_id": payee_id, "status": status, **details},
        )


class PayeeAlreadyRegistered(MandateError):
    """A payee with this name already exists in the household."""

    def __init__(self, name: str = "", **details: str) -> None:
        super().__init__(
            f"Payee {name!r} is already registered.", details={"name": name, **details}
        )
