"""Errors — the shared vocabulary for refusal, in code and on the wire.

Canonical: docs/architecture/decisions/ADR-004-api-design.md
Reference: docs/architecture/modules/authority.md#components

Two things matter here and both are domain decisions, not plumbing:

1. A refusal is a *normal, documented outcome* (HTTP 409), not a 500. Scenario 2/3/4 all end in
   a refusal, so an exception type that maps to "server broke" would misreport the product's
   core behaviour.
2. Every error carries a machine-readable `code` that lands in the error envelope and in the
   evidence payload. The console translates that code to household language; the evidence
   verifier asserts on it. It is part of the contract.

Reason codes are a closed set (module doc invariant A-5). Adding one is an architecture change.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class ErrorCode(StrEnum):
    """Closed set of error codes. Wire-stable: clients and evidence payloads depend on them.

    Canonical: docs/architecture/modules/authority.md#components
    """

    # ── generic transport / validation ──────────────────────────────────────
    VALIDATION_FAILED = "VALIDATION_FAILED"
    NOT_FOUND = "NOT_FOUND"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    CONFLICT = "CONFLICT"
    INTERNAL = "INTERNAL"

    # ── refusal reasons (ADR-007 Lock 2). Added in Phase 3; declared here so the
    #    envelope and the console copy table can be written against a stable set.
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    PAYEE_QUARANTINED = "PAYEE_QUARANTINED"
    PAYEE_FROZEN = "PAYEE_FROZEN"
    CAP_EXCEEDED = "CAP_EXCEEDED"
    DUPLICATE_INVOICE = "DUPLICATE_INVOICE"
    APPROVAL_INVALID = "APPROVAL_INVALID"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    PROPOSAL_REJECTED = "PROPOSAL_REJECTED"


#: Wording shown when an error code has no specific presentation. Deliberately dull: a generic
#: message is safer than a generated one that could leak state.
GENERIC_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.VALIDATION_FAILED: "The request could not be processed.",
    ErrorCode.NOT_FOUND: "That record does not exist.",
    ErrorCode.UNAUTHENTICATED: "Missing or invalid credentials.",
    ErrorCode.FORBIDDEN: "This action is not permitted for these credentials.",
    ErrorCode.CONFLICT: "The request conflicts with the current state.",
    ErrorCode.INTERNAL: "Something went wrong on our side.",
}


@dataclass(eq=False)
class BursarError(Exception):
    """Base class for every error that can reach the wire.

    Maps to the ADR-004 envelope:
        {"error": {"code", "message", "retryable", "correlation_id"}}
    """

    code: ErrorCode
    message: str = ""
    retryable: bool = False
    #: Structured context that lands in the envelope and the evidence payload (ids only —
    #: never amounts the client did not send, never secrets).
    details: dict[str, str] = field(default_factory=dict)
    http_status: int = 400

    def __post_init__(self) -> None:
        Exception.__init__(self, self.wire_message)

    @property
    def wire_message(self) -> str:
        return self.message or GENERIC_MESSAGES.get(self.code, "Request failed.")

    def to_envelope(self, correlation_id: str) -> dict[str, object]:
        return {
            "error": {
                "code": str(self.code),
                "message": self.wire_message,
                "retryable": self.retryable,
                "correlation_id": correlation_id,
                **({"details": self.details} if self.details else {}),
            }
        }


class ValidationError(BursarError):
    """Input shape or value is invalid. Never a domain judgement."""

    def __init__(self, message: str = "", **details: str) -> None:
        super().__init__(
            code=ErrorCode.VALIDATION_FAILED,
            message=message,
            http_status=422,
            details=details,
        )


class NotFoundError(BursarError):
    """A referenced record does not exist."""

    def __init__(self, message: str = "", **details: str) -> None:
        super().__init__(
            code=ErrorCode.NOT_FOUND, message=message, http_status=404, details=details
        )


class ForbiddenError(BursarError):
    """The credentials are valid but this actor may not do this (ADR-005 scope matrix)."""

    def __init__(self, message: str = "", **details: str) -> None:
        super().__init__(
            code=ErrorCode.FORBIDDEN, message=message, http_status=403, details=details
        )


class RefusalError(BursarError):
    """A domain refusal: the request was understood, and the answer is no.

    Canonical: docs/architecture/modules/authority.md#components

    409 rather than 500 on purpose — a refused payment is the product working. The refusal still
    produces evidence (invariant: "a refusal never produces a side effect", but it always
    produces an envelope).
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str = "",
        *,
        details: Mapping[str, str] | None = None,
        retryable: bool = False,
    ) -> None:
        """`details` is an explicit mapping, never a `**kwargs` tail.

        Two reasons, both discovered by mypy during the Authority freeze: a splat can smuggle a key named
        `retryable` (or `code`) into the constructor and silently rewrite the refusal's semantics, and a
        context error class that splats its own `**details` cannot be type-checked at all. Passing a
        mapping makes "the payload is data, not configuration" structural.
        """
        super().__init__(
            code=code,
            message=message,
            retryable=retryable,
            http_status=409,
            details=dict(details or {}),
        )


__all__ = [
    "GENERIC_MESSAGES",
    "BursarError",
    "ErrorCode",
    "ForbiddenError",
    "NotFoundError",
    "RefusalError",
    "ValidationError",
]
