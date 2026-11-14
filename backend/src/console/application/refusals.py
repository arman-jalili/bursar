"""Authority's closed refusal set, translated — the console's only refusal vocabulary (CON-07).

Canonical: docs/architecture/modules/console.md#anti-corruption-layer--field-whitelists
Reference: docs/contracts/console-contract-freeze.md §2.3

Two rules are expressed by the types rather than by convention:

1. `DenialReasonCode` mirrors Authority's closed `DenialReason` set exactly. The console cannot add a
   code: an unemitted code is a refusal the owner could never see, and a missing code is a refusal
   that cannot be rendered.
2. `refusal_copy` takes the enum, not `Iterable[str]`. An upstream string therefore fails at the
   boundary instead of printing `DIGEST_MISMATCH` on a household screen.

An empty iterable is a refusal with no reason — `RefusalReasonMissing`, never a generic
"Payment failed".
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Final

from src.console.application.errors import RefusalReasonMissing, UnknownReasonCode

__all__ = ["REFUSAL_COPY", "DenialReasonCode", "coerce_code", "refusal_copy"]


class DenialReasonCode(StrEnum):
    """Mirrors Authority's `DenialReason`; the console translates, it does not decide (ADR-007)."""

    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    PAYEE_QUARANTINED = "PAYEE_QUARANTINED"
    PAYEE_FROZEN = "PAYEE_FROZEN"
    CAP_EXCEEDED = "CAP_EXCEEDED"
    DUPLICATE_INVOICE = "DUPLICATE_INVOICE"
    APPROVAL_INVALID = "APPROVAL_INVALID"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"


#: Household language — no crypto vocabulary on any surface that reaches a payer (CON-05).
#: The key set must equal `DenialReasonCode`; a missing row is CON-07's failure mode.
REFUSAL_COPY: Final[dict[DenialReasonCode, str]] = {
    DenialReasonCode.DIGEST_MISMATCH: "Blocked: the bank details didn't match",
    DenialReasonCode.PAYEE_QUARANTINED: "Paused while we check this payee",
    DenialReasonCode.PAYEE_FROZEN: "Paused by the owner",
    DenialReasonCode.CAP_EXCEEDED: "Paused: this month's limit was reached",
    DenialReasonCode.DUPLICATE_INVOICE: "This bill was already handled",
    DenialReasonCode.APPROVAL_INVALID: "The approval didn't match this payment",
    DenialReasonCode.BUDGET_EXHAUSTED: "Paused: this month's budget is used up",
    DenialReasonCode.AMOUNT_MISMATCH: "Blocked: the amount didn't match the bill",
}


def coerce_code(code: DenialReasonCode | str) -> DenialReasonCode:
    """Turn one upstream code into the frozen enum, refusing anything outside the set (CON-07)."""
    if isinstance(code, DenialReasonCode):
        return code
    try:
        return DenialReasonCode(code)
    except ValueError as exc:
        raise UnknownReasonCode(
            f"Authority sent a reason code outside the frozen set: {code!r}"
        ) from exc


def refusal_copy(codes: Iterable[DenialReasonCode | str]) -> str:
    """Render the owner-facing reason for a refusal (scenarios 2/3/4).

    Raises:
        RefusalReasonMissing: `codes` is empty — a refusal with no reason cannot be explained.
        UnknownReasonCode: a code is outside the frozen set (CON-07).
    """
    materialised = tuple(codes)
    if not materialised:
        # CON-07: a generic "Payment failed" is the failure this rule exists to prevent.
        raise RefusalReasonMissing("a refusal with no reason code cannot be explained to the owner")

    reasons: list[str] = []
    for raw_code in materialised:
        code = coerce_code(raw_code)
        reason = REFUSAL_COPY.get(code)
        if reason is None:  # pragma: no cover - the table is complete by construction
            raise UnknownReasonCode(f"no household copy for reason code {code!r}")
        if reason not in reasons:
            reasons.append(reason)

    # Deterministic order: Authority's order is the order the owner reads them in.
    return "; ".join(reasons)
