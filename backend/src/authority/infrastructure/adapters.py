"""Adapters for the upstream ports Authority reads (ACL).

Canonical: .pi/architecture/modules/authority.md#ports-to-upstream-contexts-acl
Reference: .pi/architecture/decisions/ADR-003-cross-context-communication.md

Three adapters, each with one job:

* `SqlMandateView` is the **read-through** implementation of `MandateView`. It queries on every call and
  caches nothing, because A-6 is only enforceable if there is no remembered answer to reach for. A
  missing or unreadable record raises a *non-2xx* failure (404/503), never a default "eligible".
* `SqlOwnerDirectory` answers "which address owns this payee?" for A-15. It is deliberately not part of
  the frozen `MandateView`: verification needs the owner, issuing an intent does not.
* `UnavailableAttemptViewPort` is honest about Billing: its persistence layer does not exist yet, so
  `POST /v1/attempts/{id}/evaluate` fails closed with `503 retryable` until Billing lands. A stand-in
  that invented an invoice would silently authorise a payment, which is the failure mode ADR-007
  exists to prevent.

Reads use the caller's session, so a precondition check reads Mandate and writes Authority in one
transaction — the same instant, which is what `read_at` claims.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.authority.domain.ports import (
    AttemptView,
    ConstitutionView,
    InvoiceView,
    PayeeView,
)
from src.authority.domain.values import Money
from src.mandate.domain.services import PayeeEligibilityResolver
from src.mandate.domain.values import (
    BankDigest,
    Eligibility,
    EvmAddress,
    PayeeAddress,
    PayeeStatus,
)
from src.mandate.infrastructure.models import (
    ConstitutionVersionRow,
    HouseholdRow,
    PayeeRow,
)
from src.shared.domain.errors import BursarError, ErrorCode, NotFoundError

__all__ = [
    "SqlMandateView",
    "SqlOwnerDirectory",
    "UnavailableAttemptViewPort",
    "upstream_unavailable",
]


def upstream_unavailable(what: str, **details: str) -> BursarError:
    """A 503 that fails closed (AC 11): Rigorix must not run the command on a non-200.

    `ErrorCode.INTERNAL` with `retryable: true` is the shared vocabulary's "we could not read the
    world"; inventing an Authority-only code would give clients a second thing to learn for the same
    situation.
    """
    return BursarError(
        ErrorCode.INTERNAL,
        f"{what} could not be read; failing closed.",
        retryable=True,
        http_status=503,
        details=details,
    )


class SqlMandateView:
    """`MandateView` — read-through, no cache, fail closed (A-6, AC 11)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def constitution_in_force(self, household_id: str) -> ConstitutionView:
        result = await self._session.execute(
            select(ConstitutionVersionRow).where(
                ConstitutionVersionRow.household_id == household_id,
                ConstitutionVersionRow.status == "in_force",
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise NotFoundError(
                "no constitution is in force for this household",
                household_id=household_id,
            )
        return ConstitutionView(
            version=row.number,
            cap=Money(row.cap_micro_usdc),
            threshold=Money(row.threshold_micro_usdc),
            require_signature_for_new_payee=row.require_signature_for_new_payee,
            read_at=datetime.now(UTC),
        )

    async def household_of(self, payee_id: str) -> str:
        """The household that owns a payee — read now, from the payee row Mandate already stores."""
        household_id: str | None = await self._session.scalar(
            select(PayeeRow.household_id).where(PayeeRow.id == payee_id)
        )
        if household_id is None:
            raise NotFoundError("payee not found", payee_id=payee_id)
        return household_id

    async def constitution_for_payee(self, payee_id: str) -> ConstitutionView:
        """The in-force rules for the household that owns this payee.

        Signature verification needs the cap (to reserve capacity after an approval) but has only the
        intent, which carries no household id — by design, since the household is not part of the bytes
        the owner signs. The payee row is the one stored link, and it is read now (A-6).
        """
        household_id = await self._session.scalar(
            select(PayeeRow.household_id).where(PayeeRow.id == payee_id)
        )
        if household_id is None:
            raise NotFoundError("payee not found", payee_id=payee_id)
        return await self.constitution_in_force(household_id)

    async def payee(self, payee_id: str) -> PayeeView:
        row = await self._session.get(PayeeRow, payee_id)
        if row is None:
            raise NotFoundError("payee not found", payee_id=payee_id)
        return PayeeView(
            payee_id=row.id,
            address=PayeeAddress(row.address),
            digest=BankDigest(hash=row.verified_digest),
            status=PayeeStatus(row.status),
            read_at=datetime.now(UTC),
        )

    async def eligibility(self, payee_id: str) -> Eligibility:
        row = await self._session.get(PayeeRow, payee_id)
        if row is None:
            raise NotFoundError("payee not found", payee_id=payee_id)
        version = await self._session.execute(
            select(ConstitutionVersionRow).where(
                ConstitutionVersionRow.household_id == row.household_id,
                ConstitutionVersionRow.status == "in_force",
            )
        )
        in_force = version.scalar_one_or_none()
        require_signature = (
            in_force.require_signature_for_new_payee if in_force is not None else True
        )
        return PayeeEligibilityResolver().resolve(
            PayeeStatus(row.status), require_signature_for_new_payee=require_signature
        )


class SqlOwnerDirectory:
    """Answers "who owns this payee?" for signature verification (A-15).

    A payee belongs to exactly one household (Mandate's P-1), so the owner is reached through that row
    rather than through configuration. A hard-coded owner address would make "the recovered signer must
    equal the mandate owner" untestable against a second household.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def owner_of(self, payee_id: str) -> EvmAddress:
        result = await self._session.execute(
            select(HouseholdRow.owner_address)
            .join(PayeeRow, PayeeRow.household_id == HouseholdRow.id)
            .where(PayeeRow.id == payee_id)
        )
        address = result.scalar_one_or_none()
        if address is None:
            raise NotFoundError("owner not found for payee", payee_id=payee_id)
        return EvmAddress(address)


class UnavailableAttemptViewPort:
    """`AttemptViewPort` that fails closed until Authority reads Billing across the process boundary.

    Billing is implemented, but it lives in the **console** deployable and its own database. Reading
    `billing_attempts` from this process would find nothing and report "attempt not found" for a real
    attempt — a wrong answer that looks authoritative. Refusing with `503 retryable` is the honest
    answer until the read-through call to the console API is wired, and it keeps AC 11's status-code
    contract ("anything but 200 means do not run the command") true today.
    """

    async def load(self, attempt_id: str) -> tuple[AttemptView, InvoiceView]:
        raise upstream_unavailable("Billing", attempt_id=attempt_id)
