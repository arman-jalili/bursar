"""SC-3 / SC-5 / SC-10 — the storage layer keeps the guarantees the domain states.

Canonical: docs/contracts/settlement-contract-freeze.md §1
Reference: .pi/architecture/modules/settlement.md#repository-interfaces-owned-by-domain

Real SQLite, real adapters, real constraints. The point is the durable half of the contract:

* the write-ahead hash survives a process restart, because the row is the re-poll source (SC-3);
* one intent cannot have two orders, and one nullifier cannot be spent twice — the unique constraints
  are the last local lock, and a race loses with a domain refusal, not a driver error (SC-4, SC-5);
* receipts are append-only facts carrying gas and fee, the only input to cost (SC-10);
* drained events land in `settlement_outbox` in the same transaction (ADR-003).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.settlement.domain.errors import (
    DuplicateSettlementBlocked,
    OrderAlreadyConcluded,
)
from src.settlement.domain.ids import OrderId
from src.settlement.domain.settlement_order import SettlementOrder
from src.settlement.domain.values import ReceiptStatus, SettlementStatus
from src.settlement.infrastructure.models import SettlementOutboxRow
from src.settlement.infrastructure.repositories import (
    OutboxWriter,
    SqlChainReceiptRepository,
    SqlNullifierRepository,
    SqlSettlementOrderRepository,
)

from tests.integration.settlement.conftest import an_order, persist
from tests.unit.settlement._fixtures import a_receipt


class TestOrderPersistence:
    async def test_the_write_ahead_hash_survives_a_restart(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """SC-3 / AC-3: reload in a fresh session, re-poll the same hash — never sign a second tx."""
        order = an_order()
        await persist(factory, order)

        session = factory()
        try:
            stored = await SqlSettlementOrderRepository(session).find_by_id(order.id)
            assert stored is not None
            stored.mark_submitted("0x" + "aa" * 32, stored.amount)
            await SqlSettlementOrderRepository(session).save(stored)
            await session.commit()
        finally:
            await session.close()

        # A new session stands in for the restarted process.
        session = factory()
        try:
            reloaded = await SqlSettlementOrderRepository(session).find_by_intent(order.intent_id)
            assert reloaded is not None
            assert reloaded.tx_hash == "0x" + "aa" * 32
            assert reloaded.status is SettlementStatus.SUBMITTED
        finally:
            await session.close()

    async def test_a_second_order_for_one_intent_is_refused(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """SC-3 / SC-4 / AC-3: a replay cannot create a parallel order with a second hash."""
        order = an_order()
        await persist(factory, order)
        duplicate = SettlementOrder(
            id=OrderId("another-order"),
            intent_id=order.intent_id,
            invoice_id=order.invoice_id,
            payee_address=order.payee_address,
            amount=order.amount,
            nullifier=order.nullifier,
            network=order.network,
            status=SettlementStatus.ORDERED,
            bank_digest=order.bank_digest,
        )

        with pytest.raises(OrderAlreadyConcluded):
            await persist(factory, duplicate)

    async def test_the_frozen_facts_are_not_writable_after_insert(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """S-2: `save` moves status and hash only; the address/amount/nullifier stay as inserted."""
        order = an_order()
        await persist(factory, order)
        session = factory()
        try:
            stored = await SqlSettlementOrderRepository(session).find_by_id(order.id)
            assert stored is not None
            stored.status = SettlementStatus.ABANDONED
            await SqlSettlementOrderRepository(session).save(stored)
            await session.commit()
        finally:
            await session.close()

        session = factory()
        try:
            reloaded = await SqlSettlementOrderRepository(session).find_by_id(order.id)
            assert reloaded is not None
            assert reloaded.status is SettlementStatus.ABANDONED
            assert reloaded.amount == order.amount
            assert reloaded.payee_address == order.payee_address
            assert reloaded.nullifier.same_as(order.nullifier)
        finally:
            await session.close()


class TestNullifierLock:
    async def test_a_nullifier_cannot_be_spent_twice(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """SC-5 / AC-5: the primary key is the last local lock (scenario 6, app path)."""
        order = an_order()
        await persist(factory, order)

        session = factory()
        try:
            repo = SqlNullifierRepository(session)
            await repo.spend(order.nullifier, order.id)
            await session.commit()
        finally:
            await session.close()

        session = factory()
        try:
            repo = SqlNullifierRepository(session)
            assert await repo.is_spent(order.nullifier) is True
            with pytest.raises(DuplicateSettlementBlocked):
                await repo.spend(order.nullifier, OrderId("second-order"))
            await session.rollback()
        finally:
            await session.close()


class TestReceiptStore:
    async def test_receipts_are_append_only_and_the_latest_is_read(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """SC-7 / SC-10: a deeper confirmation is a new fact, and the re-poll reads the newest."""
        order = an_order()
        await persist(factory, order)
        session = factory()
        try:
            repo = SqlChainReceiptRepository(session)
            await repo.append(a_receipt(confirmations=0, order_id=order.id))
            await repo.append(a_receipt(confirmations=1, order_id=order.id))
            await session.commit()
        finally:
            await session.close()

        session = factory()
        try:
            latest = await SqlChainReceiptRepository(session).find_by_order(order.id)
            assert latest is not None
            assert latest.confirmations == 1
        finally:
            await session.close()

    async def test_cost_is_derived_from_receipts_only(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """SC-10 / AC-10: `CostSummary` sums receipt rows — there is no balance to disagree with."""
        order = an_order()
        await persist(factory, order)
        session = factory()
        try:
            repo = SqlChainReceiptRepository(session)
            await repo.append(a_receipt(order_id=order.id, fee_micro_usdc=51))
            await repo.append(
                a_receipt(
                    order_id=order.id,
                    status=ReceiptStatus.REVERTED,
                    revert_reason="NullifierSpent",
                    fee_micro_usdc=49,
                )
            )
            await session.commit()
        finally:
            await session.close()

        session = factory()
        try:
            receipts = await SqlChainReceiptRepository(session).list_for_day(
                datetime.now(UTC).date()
            )
            total = sum(r.fee_usdc_estimate.micro_usdc for r in receipts)
            assert total == 100
            assert all(r.gas_used > 0 and r.gas_price for r in receipts)
        finally:
            await session.close()


class TestOutbox:
    async def test_a_submission_writes_exactly_one_outbox_row(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """ADR-003: the event lands in the state's own transaction, one row per fact."""
        order = an_order()
        await persist(factory, order)
        session = factory()
        try:
            stored = await SqlSettlementOrderRepository(session).find_by_id(order.id)
            assert stored is not None
            stored.mark_submitted("0x" + "bb" * 32, stored.amount)
            await SqlSettlementOrderRepository(session).save(stored)
            await OutboxWriter(session).append(stored.pull_events())
            await session.commit()
        finally:
            await session.close()

        session = factory()
        try:
            rows = (
                (
                    await session.execute(
                        select(SettlementOutboxRow).where(
                            SettlementOutboxRow.event_name == "SettlementSubmitted"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
            assert rows[0].aggregate_id == str(order.id)
        finally:
            await session.close()
