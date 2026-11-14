"""Evidence refusal vocabulary (frozen).

Canonical: .pi/architecture/modules/evidence.md#components
Reference: docs/contracts/evidence-contract-freeze.md §3

Every refusal here extends the shared `RefusalError`, so the API layer needs **no Evidence-specific
exception handling** — a verification failure is a documented `409` with a domain code everywhere in
this context (ADR-004). Each class exists because one invariant needs it named:

    HmacMismatch         E-7  the payload (or any sealed field) no longer matches its HMAC
    AnchorMismatch       E-8  the envelope points at an anchor hash for a different envelope
    AppendOnlyViolation  E-5  a caller attempted to rewrite an existing envelope
    EnvelopeNotFound     E-6  verification was asked for an id that is not on file

Two operational failures are **not** refusals: signing and anchoring are best-effort witness work,
so they map to `503` and must never block the publisher (E-10). They are declared here so the
subscriber has one vocabulary for "the witness could not do its job".

The `details` mapping is always passed explicitly — never a `**kwargs` tail — because a splat could
smuggle a key named `retryable` or `code` into the envelope and silently rewrite the refusal.
"""

from __future__ import annotations

from src.evidence.domain.values import VerificationResult
from src.shared.domain.errors import BursarError, ErrorCode, NotFoundError, RefusalError

__all__ = [
    "AnchorMismatch",
    "AnchoringUnavailable",
    "AppendOnlyViolation",
    "EnvelopeNotFound",
    "EvidenceRefusal",
    "HmacMismatch",
    "SigningUnavailable",
]


class EvidenceRefusal(RefusalError):
    """Base for every refusal this context raises. Maps to HTTP 409 via the shared handler."""

    reason_code: str = "evidence_refused"


class HmacMismatch(EvidenceRefusal):
    """One sealed field no longer matches the HMAC; the anchor was never touched (E-7).

    `field` names the top-level envelope field that failed (`payload` for a DB edit). The demo may
    refine it to a dotted path (`payload.amount_micro_usdc`) once the original fact is available;
    the frozen contract only requires a non-empty name, so the console never renders a bare boolean.
    """

    result: VerificationResult = VerificationResult.HMAC_MISMATCH

    def __init__(self, failing_field: str = "payload", anchor_tx: str = "", **extra: str) -> None:
        super().__init__(
            ErrorCode.CONFLICT,
            "The envelope contents no longer match their HMAC.",
            details={
                "result": self.result.value,
                "field": failing_field,
                "anchor_tx": anchor_tx,
                **extra,
            },
        )
        self.reason_code = "hmac_mismatch"


class AnchorMismatch(EvidenceRefusal):
    """The envelope's hash is not the hash recorded by its anchor (E-8).

    The anchor is the independent half of tamper evidence: a locally valid HMAC still fails if the
    envelope was pointed at somebody else's on-chain record.
    """

    result: VerificationResult = VerificationResult.ANCHOR_MISMATCH

    def __init__(
        self, envelope_hash: str = "", anchor_hash: str = "", anchor_tx: str = "", **extra: str
    ) -> None:
        super().__init__(
            ErrorCode.CONFLICT,
            "The envelope does not match the hash recorded by its anchor.",
            details={
                "result": self.result.value,
                "envelope_hash": envelope_hash,
                "anchor_hash": anchor_hash,
                "anchor_tx": anchor_tx,
                **extra,
            },
        )
        self.reason_code = "anchor_mismatch"


class AppendOnlyViolation(EvidenceRefusal):
    """A caller tried to update or delete a sealed envelope (E-5).

    The repository port has no `update`/`delete`/`save`, so reaching this error means an adapter or a
    hand-written query bypassed the contract. A correction is a new envelope linked by
    `previous_hash`, never an edit.
    """

    def __init__(self, envelope_id: str = "", **extra: str) -> None:
        super().__init__(
            ErrorCode.CONFLICT,
            "Evidence envelopes are append-only; record a correction instead.",
            details={"envelope_id": envelope_id, **extra},
        )
        self.reason_code = "append_only_violation"


class EnvelopeNotFound(NotFoundError):
    """No envelope exists for the requested id (E-6)."""

    def __init__(self, envelope_id: str = "") -> None:
        super().__init__("That evidence envelope does not exist.", envelope_id=envelope_id)


class SigningUnavailable(BursarError):
    """The HMAC signer could not seal the fact (E-10).

    Operational, not a refusal: the publisher must continue and the gap is recorded. `503` because a
    retry is legitimate and the fact is not lost — only its witness is delayed.
    """

    def __init__(self, detail: str = "") -> None:
        super().__init__(
            code=ErrorCode.INTERNAL,
            message="Evidence signing is unavailable; the fact was not sealed.",
            retryable=True,
            http_status=503,
            details={"detail": detail},
        )


class AnchoringUnavailable(BursarError):
    """The anchor gateway could not write or read the on-chain hash (E-10).

    Like signing, this must not block dispatch. The envelope is stored and `UNANCHORED` remains a
    visible, re-anchorable state rather than a payment failure.
    """

    def __init__(self, detail: str = "") -> None:
        super().__init__(
            code=ErrorCode.INTERNAL,
            message="The anchor gateway is unavailable; the hash is not on-chain yet.",
            retryable=True,
            http_status=503,
            details={"detail": detail},
        )
