"""Upstream ports — the anti-corruption boundary to Mandate and Billing (frozen).

Canonical: docs/architecture/modules/authority.md#ports-to-upstream-contexts-acl
Reference: docs/contracts/authority-contract-freeze.md (A-2, A-6)

`MandateView` is the **read-through** port and the reason A-6 is enforceable: there is no
`cached_constitution()` method to reach for, only `constitution_in_force()` and `eligibility()`, both
documented as "read now". Scenario 3 (a payee frozen between approval and dispatch) passes only because
nothing in this port can serve a plan-time answer.

`AttemptViewPort` is the ACL from Billing: it returns a view type that **has no routing fields at all**,
so an agent-supplied `payee_address` cannot leak into `PaymentIntent.issue` (A-2) — there is nowhere to
put it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from src.authority.domain.values import Money
from src.mandate.domain.values import BankDigest, Eligibility, PayeeAddress, PayeeStatus

__all__ = [
    "AttemptView",
    "AttemptViewPort",
    "ConstitutionView",
    "InvoiceView",
    "MandateView",
    "PayeeView",
]


@dataclass(frozen=True, slots=True)
class ConstitutionView:
    """The in-force rules as read at one instant (A-6)."""

    version: int
    cap: Money
    threshold: Money
    require_signature_for_new_payee: bool
    read_at: datetime


@dataclass(frozen=True, slots=True)
class PayeeView:
    """A payee's verified routing and live eligibility, read at one instant (A-2, A-6)."""

    payee_id: str
    address: PayeeAddress
    digest: BankDigest
    status: PayeeStatus
    read_at: datetime


@dataclass(frozen=True, slots=True)
class InvoiceView:
    """The invoice amount, from Billing. Routing fields are absent by design (A-2)."""

    invoice_id: str
    payee_id: str
    amount: Money


@dataclass(frozen=True, slots=True)
class AttemptView:
    """What Authority may take from a proposal: identifiers and a claimed amount, nothing else.

    No `payee_address`, no `bank_digest`, no `command` — the ACL type makes A-2 structural rather than a
    rule someone has to remember to apply.
    """

    attempt_id: str
    invoice_id: str
    claimed_amount: Money | None = None


@runtime_checkable
class MandateView(Protocol):
    """Read-through access to Mandate. Implementations MUST NOT cache (A-6, AC 7)."""

    async def constitution_in_force(self, household_id: str) -> ConstitutionView:
        """The rules in force *now*."""
        ...

    async def payee(self, payee_id: str) -> PayeeView:
        """The payee's verified address, digest and current status — read now, never remembered."""
        ...

    async def eligibility(self, payee_id: str) -> Eligibility:
        """Authority's dispatch-time question, answered by Mandate at this instant (FR-012)."""
        ...


class AttemptViewPort(Protocol):
    """ACL from Billing: load an attempt and its invoice, exposing no routing fields (A-2)."""

    async def load(self, attempt_id: str) -> tuple[AttemptView, InvoiceView]:
        """Return the attempt and its invoice. Raises Billing's NotFound for an unknown attempt."""
        ...
