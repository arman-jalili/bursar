"""SQLAlchemy adapters for the ports in `src/settlement/domain/repositories.py`.

Canonical: .pi/architecture/modules/settlement.md#repository-interfaces-owned-by-domain
Reference: docs/contracts/settlement-contract-freeze.md (SC-3, SC-5, SC-7, SC-10)

These are the only classes in the module that know a database exists. They **never commit**: the unit of
work in `src/shared/application/unit_of_work.py` owns the transaction (ADR-002), which is what makes
"the hash is persisted in the same transaction that precedes broadcast" a checkable ordering (SC-3).

Every `add`/`spend` flushes and translates an `IntegrityError` into the domain refusal. That matters
beyond tidiness: the unique constraints are the concurrency backstop for one-order-per-intent (SC-4) and
one-spend-per-nullifier (SC-5), and a caller must receive `OrderAlreadyConcluded` /
`DuplicateSettlementBlocked`, not a driver-specific error the API would report as a 500.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.authority.domain.ids import IntentId
from src.settlement.domain.chain_receipt import ChainReceipt
from src.settlement.domain.errors import DuplicateSettlementBlocked, OrderAlreadyConcluded
from src.settlement.domain.ids import OrderId
from src.settlement.domain.repositories import (
    ChainReceiptRepository,
    NullifierRepository,
    SettlementOrderRepository,
)
from src.settlement.domain.settlement_order import SettlementOrder
from src.settlement.domain.values import Nullifier
from src.settlement.infrastructure.mappers import (
    events_to_outbox,
    order_to_domain,
    order_to_row,
    receipt_to_domain,
    receipt_to_row,
)
from src.settlement.infrastructure.models import (
    SettlementNullifierRow,
    SettlementOrderRow,
    SettlementOutboxRow,
    SettlementReceiptRow,
)
from src.shared.domain.event import DomainEvent

__all__ = [
    "OutboxWriter",
    "SqlChainReceiptRepository",
    "SqlNullifierRepository",
    "SqlSettlementOrderRepository",
    "find_nullifier_spend",
    "list_orders",
]


def _integrity_text(exc: IntegrityError) -> str:
    """The constraint name from a driver-specific error, lower-cased for matching."""
    return str(getattr(exc, "orig", exc)).lower()


class OutboxWriter:
    """Appends drained events to `settlement_outbox` inside the caller's transaction (ADR-003)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, events: tuple[DomainEvent, ...]) -> None:
        for row in events_to_outbox(events):
            self._session.add(SettlementOutboxRow(**row))


class SqlSettlementOrderRepository(SettlementOrderRepository):
    """`SettlementOrderRepository` adapter — the write-ahead store (SC-3)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, order: SettlementOrder) -> None:
        if await self.find_by_intent(order.intent_id) is not None:
            # The service-level guard, so the caller gets the domain refusal even without a race.
            raise OrderAlreadyConcluded(order_id=str(order.id), status=order.status.value)
        self._session.add(order_to_row(order))
        try:
            await self._session.flush()
        except IntegrityError as exc:
            text = _integrity_text(exc)
            if "nullifier" in text:
                raise DuplicateSettlementBlocked(
                    nullifier=order.nullifier.value, order_id=str(order.id)
                ) from exc
            # `uq_settlement_orders_intent` (or the tx-hash constraint) raced us (SC-3, SC-4).
            raise OrderAlreadyConcluded(order_id=str(order.id), status=order.status.value) from exc
        order.version = 1

    async def find_by_id(self, id_: OrderId) -> SettlementOrder | None:
        row = await self._session.get(SettlementOrderRow, str(id_))
        return order_to_domain(row) if row else None

    async def find_by_intent(self, intent_id: IntentId) -> SettlementOrder | None:
        result = await self._session.execute(
            select(SettlementOrderRow).where(SettlementOrderRow.intent_id == str(intent_id))
        )
        row = result.scalar_one_or_none()
        return order_to_domain(row) if row else None

    async def save(self, order: SettlementOrder) -> None:
        row = await self._session.get(SettlementOrderRow, str(order.id))
        if row is None:
            self._session.add(order_to_row(order))
            order.version = 1
            return
        # Only the fields the state machine may move. The frozen facts (address, amount, nullifier) are
        # not writable after insert, which is S-2 in the storage layer.
        row.status = order.status.value
        row.tx_hash = order.tx_hash
        # Written together with the hash: the write-ahead record is only re-broadcastable while the
        # signed bytes are stored beside it (SC-3).
        row.raw_transaction = order.raw_transaction
        row.version = row.version + 1
        order.version = row.version


class SqlNullifierRepository(NullifierRepository):
    """`NullifierRepository` adapter — the database is the last local lock (SC-5)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def is_spent(self, nullifier: Nullifier) -> bool:
        return await self._session.get(SettlementNullifierRow, nullifier.value) is not None

    async def spend(self, nullifier: Nullifier, order_id: OrderId) -> None:
        self._session.add(SettlementNullifierRow(nullifier=nullifier.value, order_id=str(order_id)))
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # Two racing use cases both observed "unspent"; the primary key makes exactly one win.
            raise DuplicateSettlementBlocked(
                nullifier=nullifier.value, order_id=str(order_id)
            ) from exc


class SqlChainReceiptRepository(ChainReceiptRepository):
    """`ChainReceiptRepository` adapter — append-only chain facts, the only cost source (SC-10)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, receipt: ChainReceipt) -> None:
        self._session.add(receipt_to_row(receipt))
        await self._session.flush()

    async def find_by_order(self, order_id: OrderId) -> ChainReceipt | None:
        result = await self._session.execute(
            select(SettlementReceiptRow)
            .where(SettlementReceiptRow.order_id == str(order_id))
            .order_by(SettlementReceiptRow.observed_at.desc(), SettlementReceiptRow.id.desc())
        )
        row = result.scalars().first()
        return receipt_to_domain(row) if row else None

    async def list_for_day(self, day: date) -> tuple[ChainReceipt, ...]:
        # SQLite stores `func.now()` as naive UTC, so the bounds are naive too; a tz-aware bound would
        # compare an offset string against a naive one and silently match nothing.
        start = datetime.combine(day, time.min)
        end = start + timedelta(days=1)
        result = await self._session.execute(
            select(SettlementReceiptRow)
            .where(
                SettlementReceiptRow.observed_at >= start,
                SettlementReceiptRow.observed_at < end,
            )
            .order_by(SettlementReceiptRow.observed_at, SettlementReceiptRow.id)
        )
        return tuple(receipt_to_domain(row) for row in result.scalars().all())


async def list_orders(
    session: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[SettlementOrder]:
    """Read-model query for `GET /v1/orders`.

    A read model, not an aggregate load through the port: listing is not a domain decision, and
    `SettlementOrderRepository` deliberately has no `list` method (a port that grows read models stops
    being a consistency boundary). Newest first, because the console shows the latest settlements.
    """
    statement = (
        select(SettlementOrderRow)
        .order_by(SettlementOrderRow.created_at.desc(), SettlementOrderRow.id.desc())
        .limit(limit)
    )
    if status:
        statement = statement.where(SettlementOrderRow.status == status)
    result = await session.execute(statement)
    return [order_to_domain(row) for row in result.scalars().all()]


async def find_nullifier_spend(session: AsyncSession, nullifier: Nullifier) -> str | None:
    """The order that spent this marker, or None. Read-only companion to `is_spent`."""
    row = await session.get(SettlementNullifierRow, nullifier.value)
    return row.order_id if row else None
