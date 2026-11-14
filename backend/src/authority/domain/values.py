"""Authority value objects and closed sets (frozen).

Canonical: docs/architecture/modules/authority.md#components
Reference: docs/contracts/authority-contract-freeze.md (A-5)

`Money` is imported, not redefined: the shared kernel owns one definition (ADR-002), and a second money
type inside Authority would eventually disagree with the ledger about rounding.

`DeterminationVerdict` and `DenialReason` are **closed sets**. A verdict that is not one of three, or a
denial without a code from the list, cannot be constructed — which is what makes a refusal explainable
(A-5, A-7) and assertable in a test.
"""

from __future__ import annotations

import enum

from src.shared.domain.money import Money

__all__ = ["DenialReason", "DeterminationVerdict", "Money"]


class DeterminationVerdict(enum.StrEnum):
    """The three answers Authority may give. There is no fourth, and there is no "maybe".

    `ALLOW` is the only verdict that permits dispatch; `ESCALATE` permits it *after* the owner signs
    (A-13…A-15); `DENY` never does (A-8).
    """

    ALLOW = "allow"
    DENY = "deny"
    ESCALATE = "escalate"


class DenialReason(enum.StrEnum):
    """Closed set of refusal codes (A-5).

    Each code is a *cause*, not a message: the console translates it into household language and the
    evidence envelope seals it, so a free-text reason would be unauditable. Adding a code here is a
    contract change, not a refactor.
    """

    DIGEST_MISMATCH = "digest_mismatch"
    PAYEE_QUARANTINED = "payee_quarantined"
    PAYEE_FROZEN = "payee_frozen"
    CAP_EXCEEDED = "cap_exceeded"
    DUPLICATE_INVOICE = "duplicate_invoice"
    APPROVAL_INVALID = "approval_invalid"
    BUDGET_EXHAUSTED = "budget_exhausted"
    AMOUNT_MISMATCH = "amount_mismatch"

    @property
    def is_escalation(self) -> bool:
        """No code is an escalation: escalation is decided by newness and threshold, not by a refusal."""
        return False
