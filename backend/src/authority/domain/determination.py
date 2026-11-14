"""Determination — the verdict, with the rules it consulted (frozen).

Canonical: docs/architecture/modules/authority.md#aggregate-determination
Reference: docs/contracts/authority-contract-freeze.md (A-5 … A-8)

    A-5  a DENY carries at least one code from the closed `DenialReason` set
    A-6  `constitution_version` and `payee_status_read` come from the **same read** as the verdict,
         with `read_at` — never from a plan-time snapshot
    A-7  a determination cannot exist without a reason (deny) or without a version (always)
    A-8  a DENY produces no reservation and no dispatch

A-6 is the rule scenario 3 exists to catch: the payee was eligible when planned and frozen before
dispatch. Recording the version and the payee status *from the read that produced the verdict*, with its
timestamp, is what makes "we judged it against the rules in force at that instant" a checkable statement
rather than a claim.

A-7 is enforced at construction (immutability + a raising `__post_init__` in Phase B), so an unexplainable
verdict cannot be built and then explained later.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from src.authority.domain.errors import DeterminationWithoutReason, DispatchWithoutAuthority
from src.authority.domain.ids import DeterminationId, IntentId, new_id
from src.authority.domain.values import DenialReason, DeterminationVerdict, Money
from src.mandate.domain.values import PayeeStatus

__all__ = ["Determination"]


@dataclass(frozen=True, slots=True)
class Determination:
    """An immutable record of judgement. History cannot be rewritten, so it cannot be re-argued."""

    id: DeterminationId
    intent_id: IntentId
    verdict: DeterminationVerdict
    reason_codes: tuple[DenialReason, ...]
    constitution_version: int
    payee_status_read: PayeeStatus
    read_at: datetime
    ledger_snapshot: Money

    def __post_init__(self) -> None:
        """A-7: no verdict without the version it was judged against."""
        if not self.constitution_version:
            raise DeterminationWithoutReason("missing constitution_version")
        if self.verdict is DeterminationVerdict.DENY and not self.reason_codes:
            raise DeterminationWithoutReason("a denial must carry at least one code")

    @classmethod
    def allow(
        cls,
        *,
        intent_id: IntentId,
        constitution_version: int,
        payee_status_read: PayeeStatus,
        read_at: datetime,
        ledger_snapshot: Money,
    ) -> Determination:
        """Permit dispatch. Carries no reason codes — an allowance needs no excuse (A-5)."""
        return cls(
            id=DeterminationId(new_id()),
            intent_id=intent_id,
            verdict=DeterminationVerdict.ALLOW,
            reason_codes=(),
            constitution_version=constitution_version,
            payee_status_read=payee_status_read,
            read_at=read_at,
            ledger_snapshot=ledger_snapshot,
        )

    @classmethod
    def deny(
        cls,
        *,
        intent_id: IntentId,
        reasons: Sequence[DenialReason],
        constitution_version: int,
        payee_status_read: PayeeStatus,
        read_at: datetime,
        ledger_snapshot: Money,
    ) -> Determination:
        """Refuse with at least one code (A-5).

        Raises:
            DeterminationWithoutReason: `reasons` is empty or holds something outside the closed set
                (A-7) — a refusal nobody can explain is indistinguishable from a bug.
        """
        if not reasons:
            raise DeterminationWithoutReason("a denial must carry at least one code")
        codes: list[DenialReason] = []
        for reason in reasons:
            try:
                codes.append(DenialReason(reason))
            except ValueError as exc:
                raise DeterminationWithoutReason(
                    f"{reason!r} is not a code in the closed DenialReason set"
                ) from exc
        return cls(
            id=DeterminationId(new_id()),
            intent_id=intent_id,
            verdict=DeterminationVerdict.DENY,
            reason_codes=tuple(codes),
            constitution_version=constitution_version,
            payee_status_read=payee_status_read,
            read_at=read_at,
            ledger_snapshot=ledger_snapshot,
        )

    @classmethod
    def escalate(
        cls,
        *,
        intent_id: IntentId,
        constitution_version: int,
        payee_status_read: PayeeStatus,
        read_at: datetime,
        ledger_snapshot: Money,
    ) -> Determination:
        """Neither refused nor dispatched: the owner must sign this exact intent (A-4, A-13)."""
        return cls(
            id=DeterminationId(new_id()),
            intent_id=intent_id,
            verdict=DeterminationVerdict.ESCALATE,
            reason_codes=(),
            constitution_version=constitution_version,
            payee_status_read=payee_status_read,
            read_at=read_at,
            ledger_snapshot=ledger_snapshot,
        )

    @property
    def permits_dispatch(self) -> bool:
        """True only for ALLOW. ESCALATE permits dispatch *after* an approval, never on its own (A-8)."""
        return self.verdict is DeterminationVerdict.ALLOW

    def assert_not_a_refusal(self) -> None:
        """Guard used before any side effect, so a DENY can never reserve or dispatch (A-8).

        Raises:
            DispatchWithoutAuthority: the verdict is DENY.
        """
        if self.verdict is DeterminationVerdict.DENY:
            raise DispatchWithoutAuthority(self.verdict.value)
