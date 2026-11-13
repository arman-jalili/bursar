"""SQLAlchemy adapters for the ports in `src/mandate/domain/repositories.py`.

Canonical: .pi/architecture/modules/mandate.md#components
Reference: .pi/architecture/decisions/ADR-002-data-storage-strategy.md

These are the only classes in the module that know a database exists. They **never commit**: the
unit of work in `src/shared/application/unit_of_work.py` owns the transaction (ADR-002), which is what
makes "one application service = one atomic change" checkable.

Optimistic concurrency: `save` compares the aggregate's `version` with the stored one and raises
`StaleAggregateError` on mismatch, so two concurrent requests cannot both write a payee that quarantined
in between.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.mandate.domain.constitution import Constitution, ConstitutionVersion
from src.mandate.domain.errors import MandateError
from src.mandate.domain.household import Household
from src.mandate.domain.ids import ConstitutionId, HouseholdId, PayeeId
from src.mandate.domain.payee import Payee
from src.mandate.domain.repositories import (
    ConstitutionRepository,
    HouseholdRepository,
    PayeeRepository,
)
from src.mandate.infrastructure.mappers import (
    constitution_to_domain,
    constitution_to_row,
    events_to_outbox,
    household_to_domain,
    household_to_row,
    payee_to_domain,
    payee_to_row,
    version_to_domain,
)
from src.mandate.infrastructure.models import (
    ConstitutionRow,
    ConstitutionVersionRow,
    HouseholdRow,
    OutboxRow,
    PayeeRow,
)
from src.shared.domain.errors import ErrorCode
from src.shared.domain.event import DomainEvent

__all__ = [
    "OutboxWriter",
    "SqlConstitutionRepository",
    "SqlHouseholdRepository",
    "SqlPayeeRepository",
    "StaleAggregateError",
]


class StaleAggregateError(MandateError):
    """The stored version moved on since this aggregate was read (ADR-002 optimistic locking)."""

    default_code = ErrorCode.CONFLICT
    default_status = 409


class OutboxWriter:
    """Appends drained events to `mandate_outbox` inside the caller's transaction (ADR-003)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, events: tuple[DomainEvent, ...]) -> None:
        for row in events_to_outbox(events):
            self._session.add(OutboxRow(**row))


class SqlHouseholdRepository(HouseholdRepository):
    """`HouseholdRepository` adapter."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_id(self, id_: HouseholdId) -> Household | None:
        row = await self._session.get(HouseholdRow, str(id_))
        return household_to_domain(row) if row else None

    async def find_by_owner_address(self, address: str) -> Household | None:
        result = await self._session.execute(
            select(HouseholdRow).where(HouseholdRow.owner_address == address)
        )
        row = result.scalar_one_or_none()
        return household_to_domain(row) if row else None

    async def save(self, household: Household) -> None:
        expected, payload = household.version, household_to_row(household)
        existing = await self._session.get(HouseholdRow, payload.id)
        if existing is None:
            payload.version = expected + 1
            self._session.add(payload)
        else:
            if existing.version != expected:
                raise StaleAggregateError(
                    "the household changed while you were working; reload and retry",
                    details={"aggregate_id": payload.id},
                )
            for column in (
                "owner_id",
                "owner_address",
                "owner_name",
                "payer_id",
                "payer_name",
                "payer_contact",
                "agent_id",
                "agent_key_id",
                "agent_enabled",
                "constitution_id",
                "version",
            ):
                setattr(existing, column, getattr(payload, column))
            existing.version = expected + 1
        household.version = expected + 1


class SqlConstitutionRepository(ConstitutionRepository):
    """`ConstitutionRepository` adapter. `find_in_force` reads through on every call (FR-012)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_id(self, id_: ConstitutionId) -> Constitution | None:
        result = await self._session.execute(
            select(ConstitutionRow).where(ConstitutionRow.id == str(id_))
        )
        row = result.scalar_one_or_none()
        return constitution_to_domain(row) if row else None

    async def find_in_force(self, household_id: HouseholdId) -> ConstitutionVersion:
        result = await self._session.execute(
            select(ConstitutionVersionRow).where(
                ConstitutionVersionRow.household_id == str(household_id),
                ConstitutionVersionRow.status == "in_force",
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            from src.mandate.domain.errors import ConstitutionCorrupted

            raise ConstitutionCorrupted(0, household_id=str(household_id))
        return version_to_domain(row)

    async def find_version(
        self, constitution_id: ConstitutionId, number: int
    ) -> ConstitutionVersion:
        result = await self._session.execute(
            select(ConstitutionVersionRow).where(
                ConstitutionVersionRow.constitution_id == str(constitution_id),
                ConstitutionVersionRow.number == number,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise KeyError(f"constitution {constitution_id} has no version {number}")
        return version_to_domain(row)

    async def save(self, constitution: Constitution) -> None:
        expected = constitution.version
        row = await self._session.get(ConstitutionRow, str(constitution.id))
        if row is None:
            payload = constitution_to_row(constitution)
            payload.version = expected + 1
            self._session.add(payload)
        else:
            if row.version != expected:
                raise StaleAggregateError(
                    "the constitution changed while you were working; reload and retry",
                    details={"aggregate_id": row.id},
                )
            known = {version.number for version in row.versions}
            for version in constitution.versions():
                if version.number not in known:
                    self._session.add(
                        ConstitutionVersionRow(
                            constitution_id=row.id,
                            household_id=row.household_id,
                            number=version.number,
                            cap_micro_usdc=version.cap.micro_usdc,
                            threshold_micro_usdc=version.threshold.micro_usdc,
                            require_signature_for_new_payee=version.require_signature_for_new_payee,
                            content_hash=version.content_hash,
                            status=version.status.value,
                        )
                    )
                else:
                    stored = next(v for v in row.versions if v.number == version.number)
                    stored.status = version.status.value
            row.version = expected + 1
        constitution.version = expected + 1


class SqlPayeeRepository(PayeeRepository):
    """`PayeeRepository` adapter."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_id(self, id_: PayeeId) -> Payee | None:
        row = await self._session.get(PayeeRow, str(id_))
        return payee_to_domain(row) if row else None

    async def find_by_household(self, household_id: HouseholdId) -> list[Payee]:
        result = await self._session.execute(
            select(PayeeRow)
            .where(PayeeRow.household_id == str(household_id))
            .order_by(PayeeRow.created_at, PayeeRow.name)
        )
        return [payee_to_domain(row) for row in result.scalars()]

    async def find_by_name(self, household_id: HouseholdId, name: str) -> Payee | None:
        result = await self._session.execute(
            select(PayeeRow).where(
                PayeeRow.household_id == str(household_id), PayeeRow.name == name
            )
        )
        row = result.scalar_one_or_none()
        return payee_to_domain(row) if row else None

    async def save(self, payee: Payee) -> None:
        expected, payload = payee.version, payee_to_row(payee)
        existing = await self._session.get(PayeeRow, payload.id)
        if existing is None:
            payload.version = expected + 1
            self._session.add(payload)
        else:
            if existing.version != expected:
                raise StaleAggregateError(
                    "the payee changed while you were working; reload and retry",
                    details={"aggregate_id": payload.id},
                )
            existing.name = payload.name
            existing.address = payload.address
            existing.verified_digest = payload.verified_digest
            existing.status = payload.status
            existing.version = expected + 1
        payee.version = expected + 1

    async def count_by_household(self, household_id: HouseholdId) -> int:
        result = await self._session.execute(
            select(PayeeRow.id).where(PayeeRow.household_id == str(household_id))
        )
        return len(result.scalars().all())

    async def delete_all(self, household_id: HouseholdId) -> None:
        """Demo reset only — the aggregate itself has no delete operation."""
        await self._session.execute(
            delete(PayeeRow).where(PayeeRow.household_id == str(household_id))
        )
