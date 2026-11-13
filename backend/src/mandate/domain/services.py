"""Mandate domain services — the rules that need two aggregates at once.

Canonical: .pi/architecture/modules/mandate.md#components
Reference: .pi/architecture/modules/mandate.md#frozen-contracts-v1--2026-11-13

`EligibilityResolver` is the one rule that genuinely needs both the payee and the constitution: a
`NEW` payee escalates only when the in-force version requires a signature for new payees. Putting it
on `Payee` would force the aggregate to hold constitution state; putting it on `Constitution` would
make the constitution know about payees.

`Eligibility` carries a `ReasonCode`, never prose, because the reason is sealed into evidence and
translated by the console copy table.
"""

from __future__ import annotations

from src.mandate.domain.ports import EligibilityResolver
from src.mandate.domain.values import Eligibility, PayeeStatus, ReasonCode

__all__ = ["PayeeEligibilityResolver"]


class PayeeEligibilityResolver(EligibilityResolver):
    """Map a payee status to a verdict, given the constitution's new-payee flag (FR-012)."""

    def resolve(
        self, status: PayeeStatus, *, require_signature_for_new_payee: bool = True
    ) -> Eligibility:
        if status is PayeeStatus.ELIGIBLE:
            return Eligibility.allow()
        if status is PayeeStatus.NEW:
            # The flag exists so an owner who trusts their payee list can auto-pay a first bill.
            if require_signature_for_new_payee:
                return Eligibility.escalate(ReasonCode.NEW_PAYEE.value)
            return Eligibility.allow()
        if status is PayeeStatus.QUARANTINED:
            return Eligibility.deny(ReasonCode.PAYEE_QUARANTINED.value)
        return Eligibility.deny(ReasonCode.PAYEE_FROZEN.value)
