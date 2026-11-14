"""Integration — Mandate persistence adapters (AC #12: events land in the same transaction).

Canonical: docs/architecture/modules/mandate.md#components
Reference: docs/architecture/decisions/ADR-002-data-storage-strategy.md

Run against a real SQLite file with the real pragmas: the partial unique index (H-4) and the
optimistic-concurrency check are storage behaviours, and an in-memory fake would prove neither.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.mandate.domain.constitution import Constitution
from src.mandate.domain.entities import Agent, Owner, Payer
from src.mandate.domain.errors import ConstitutionCorrupted
from src.mandate.domain.household import Household
from src.mandate.domain.ids import AgentId, HouseholdId, OwnerId, PayerId, new_id
from src.mandate.domain.payee import Payee
from src.mandate.domain.values import (
    BankDigest,
    Cap,
    DisplayName,
    EvmAddress,
    PartyRef,
    PayeeAddress,
    PayeeName,
    Role,
    RoutingDetails,
    Threshold,
    usdc_to_micro,
)
from src.mandate.infrastructure.models import Base, OutboxRow
from src.mandate.infrastructure.repositories import (
    OutboxWriter,
    SqlConstitutionRepository,
    SqlHouseholdRepository,
    SqlPayeeRepository,
    StaleAggregateError,
)
from src.shared.application.unit_of_work import session_scope
from src.shared.infrastructure.db import build_engine, build_session_factory

OWNER = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
PAYEE = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"


class FakeProof:
    def __init__(self, valid: bool = True) -> None:
        self.valid = valid
        self.seen: list[tuple[object, ...]] = []

    def signs(self, *subjects: object) -> bool:
        self.seen.append(subjects)
        return self.valid


@pytest.fixture
async def factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = build_engine(f"sqlite+aiosqlite:///{tmp_path / 'mandate.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield build_session_factory(engine)
    finally:
        await engine.dispose()


@pytest.fixture
def household_actor() -> PartyRef:
    return PartyRef(role=Role.OWNER, id="owner-1")


def _constitution(household_id: HouseholdId) -> Constitution:
    return Constitution.initial(
        household_id,
        Cap(micro_usdc=usdc_to_micro("150")),
        Threshold(micro_usdc=usdc_to_micro("25")),
    )


def _household(constitution: Constitution, actor: PartyRef) -> Household:
    return Household.open(
        owner=Owner(id=OwnerId(new_id()), address=EvmAddress(OWNER), name=DisplayName("Dana")),
        payer=Payer(id=PayerId(new_id()), name=DisplayName("Mum")),
        agent=Agent(id=AgentId(new_id()), key_id="key-1"),
        constitution=constitution,
        actor=actor,
    )


def _payee(
    household_id: HouseholdId, actor: PartyRef, account: str = "DE89370400440532013000"
) -> Payee:
    return Payee.register(
        household_id=household_id,
        name=PayeeName("Northwind Energy"),
        address=PayeeAddress(PAYEE),
        digest=BankDigest.from_routing_details(
            RoutingDetails(scheme="sepa", account_number=account)
        ),
        actor=actor,
        proof=FakeProof(),
    )


class TestConstitutionPersistence:
    async def test_round_trips_a_lineage_and_reads_in_force(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        constitution = _constitution(HouseholdId(new_id()))

        async with session_scope(factory) as session:
            await SqlConstitutionRepository(session).save(constitution)

        async with session_scope(factory) as session:
            repo = SqlConstitutionRepository(session)
            loaded = await repo.find_by_id(constitution.id)
            live = await repo.find_in_force(constitution.household_id)

        assert loaded is not None
        assert live.number == 1
        assert live.cap.micro_usdc == usdc_to_micro("150")

    async def test_append_persists_a_new_version_and_supersedes(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        actor = PartyRef(Role.OWNER, "owner-1")
        constitution = _constitution(HouseholdId(new_id()))
        async with session_scope(factory) as session:
            await SqlConstitutionRepository(session).save(constitution)

        async with session_scope(factory) as session:
            repo = SqlConstitutionRepository(session)
            loaded = await repo.find_by_id(constitution.id)
            assert loaded is not None
            loaded.append(
                Cap(micro_usdc=usdc_to_micro("300")),
                Threshold(micro_usdc=usdc_to_micro("50")),
                True,
                actor,
                FakeProof(),
            )
            await repo.save(loaded)

        async with session_scope(factory) as session:
            repo = SqlConstitutionRepository(session)
            live = await repo.find_in_force(constitution.household_id)
            old = await repo.find_version(constitution.id, 1)

        assert live.number == 2 and live.cap.micro_usdc == usdc_to_micro("300")
        assert old.status.value == "superseded", "H-7: history stays addressable"

    async def test_two_in_force_versions_are_refused_by_the_database(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """H-4 as a partial unique index: the storage layer cannot hold two live versions."""
        from src.mandate.infrastructure.models import ConstitutionVersionRow

        household_id = HouseholdId(new_id())
        constitution = _constitution(household_id)
        async with session_scope(factory) as session:
            await SqlConstitutionRepository(session).save(constitution)

        with pytest.raises(IntegrityError):  # the partial unique index refuses a second live row
            async with session_scope(factory) as session:
                session.add(
                    ConstitutionVersionRow(
                        constitution_id=constitution.id,
                        household_id=str(household_id),
                        number=99,
                        cap_micro_usdc=1,
                        threshold_micro_usdc=0,
                        require_signature_for_new_payee=True,
                        content_hash="x" * 64,
                        status="in_force",
                    )
                )

    async def test_missing_in_force_version_raises_corruption(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        with pytest.raises(ConstitutionCorrupted):
            async with session_scope(factory) as session:
                await SqlConstitutionRepository(session).find_in_force(HouseholdId("never-seen"))


class TestHouseholdPersistence:
    async def test_round_trips_parties_and_finds_by_owner(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        actor = PartyRef(Role.OWNER, "owner-1")
        constitution = _constitution(HouseholdId(new_id()))
        household = _household(constitution, actor)

        async with session_scope(factory) as session:
            await SqlHouseholdRepository(session).save(household)

        async with session_scope(factory) as session:
            loaded = await SqlHouseholdRepository(session).find_by_owner_address(OWNER)

        assert loaded is not None
        assert loaded.owner.address.value == OWNER
        assert loaded.agent.key_id == "key-1"


class TestPayeePersistence:
    async def test_round_trips_and_preserves_status(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        actor = PartyRef(Role.OWNER, "owner-1")
        payee = _payee(HouseholdId(new_id()), actor)

        async with session_scope(factory) as session:
            await SqlPayeeRepository(session).save(payee)

        async with session_scope(factory) as session:
            loaded = await SqlPayeeRepository(session).find_by_id(payee.id)

        assert loaded is not None
        assert loaded.verified_digest == payee.verified_digest
        assert loaded.status.value == "new"
        assert loaded.pending_events == (), "rehydration must not replay creation events"

    async def test_quarantine_is_persisted(self, factory: async_sessionmaker[AsyncSession]) -> None:
        actor = PartyRef(Role.OWNER, "owner-1")
        payee = _payee(HouseholdId(new_id()), actor)
        async with session_scope(factory) as session:
            await SqlPayeeRepository(session).save(payee)

        async with session_scope(factory) as session:
            repo = SqlPayeeRepository(session)
            loaded = await repo.find_by_id(payee.id)
            assert loaded is not None
            loaded.review_presented_digest(
                BankDigest.from_routing_details(
                    RoutingDetails(scheme="sepa", account_number="GB33BUKB20201555555555")
                ),
                invoice_id="inv-12",
            )
            await repo.save(loaded)

        async with session_scope(factory) as session:
            reloaded = await SqlPayeeRepository(session).find_by_id(payee.id)

        assert reloaded is not None
        assert reloaded.status.value == "quarantined"
        assert reloaded.address.value == PAYEE, "the destination never moves on quarantine"

    async def test_stale_write_is_rejected(self, factory: async_sessionmaker[AsyncSession]) -> None:
        """Optimistic concurrency: two readers, one writer wins."""
        actor = PartyRef(Role.OWNER, "owner-1")
        payee = _payee(HouseholdId(new_id()), actor)
        async with session_scope(factory) as session:
            await SqlPayeeRepository(session).save(payee)

        async with session_scope(factory) as session:
            first = await SqlPayeeRepository(session).find_by_id(payee.id)
        async with session_scope(factory) as session:
            second = await SqlPayeeRepository(session).find_by_id(payee.id)
        assert first is not None and second is not None

        async with session_scope(factory) as session:
            first.freeze(PartyRef(Role.OWNER, "owner-1"))
            await SqlPayeeRepository(session).save(first)

        with pytest.raises(StaleAggregateError):
            async with session_scope(factory) as session:
                await SqlPayeeRepository(session).save(second)

    async def test_payee_name_is_unique_per_household(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        household_id = HouseholdId(new_id())
        actor = PartyRef(Role.OWNER, "owner-1")
        async with session_scope(factory) as session:
            await SqlPayeeRepository(session).save(_payee(household_id, actor))

        with pytest.raises(IntegrityError):  # uq_mandate_payee_name
            async with session_scope(factory) as session:
                await SqlPayeeRepository(session).save(_payee(household_id, actor, "OTHER"))


class TestOutbox:
    async def test_events_are_written_in_the_same_transaction(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """AC #12: state and events commit together, or neither does."""
        actor = PartyRef(Role.OWNER, "owner-1")
        payee = _payee(HouseholdId(new_id()), actor)

        async with session_scope(factory) as session:
            repo = SqlPayeeRepository(session)
            outbox = OutboxWriter(session)
            await repo.save(payee)
            await outbox.append(payee.pull_events())

        async with session_scope(factory) as session:
            rows = (await session.execute(select(OutboxRow))).scalars().all()

        assert [row.event_name for row in rows] == ["PayeeRegistered"]
        assert rows[0].published_at is None, "publishing is the dispatcher's job, not the writer's"

    async def test_a_rollback_discards_state_and_events_together(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        actor = PartyRef(Role.OWNER, "owner-1")
        payee = _payee(HouseholdId(new_id()), actor)

        with pytest.raises(RuntimeError):
            async with session_scope(factory) as session:
                repo = SqlPayeeRepository(session)
                await repo.save(payee)
                await OutboxWriter(session).append(payee.pull_events())
                raise RuntimeError("boom")

        async with session_scope(factory) as session:
            payees = (await session.execute(text("SELECT count(*) FROM mandate_payees"))).scalar()
            events = (await session.execute(text("SELECT count(*) FROM mandate_outbox"))).scalar()

        assert payees == 0 and events == 0
