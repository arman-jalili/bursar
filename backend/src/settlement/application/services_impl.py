"""Concrete Settlement read side — the services that can run before the chain adapter exists.

Canonical: .pi/architecture/modules/settlement.md#application-services
Reference: docs/contracts/settlement-contract-freeze.md §2.10

Scope, stated honestly: `GetReceipt`, `ListOrders`, `CostSummary` and `AnchorHash` are implemented here
and wired into the console composition root (see `src/apps/console_api/app.py`). They need a database
and, for `AnchorHash`, a `ChainGateway` port — nothing they cannot get.

`DispatchPayment` is implemented in `application/dispatch.py`: gate → sign locally → persist the hash
and the signed bytes (SC-3) → governed broadcast. `SettleOnce` is **not** implemented, and that is still
a blocker, not an omission:

* `SettlementStatus` declares `PENDING` and `ABANDONED`, and the module doc's state diagram transitions
  into them, but `SettlementOrder` has no intention method to make those moves. An application service
  would have to write `order.status = …` from outside, which is exactly what the aggregate forbids.
* Nothing decides finality on the write path yet: a receipt is read once as evidence after the broadcast,
  and the `PENDING`/`CONFIRMED`/`REVERTED` conclusion is `SettleOnce`'s (SC-6, SC-7). An order today stops
  at `SUBMITTED`.

B-2 (the missing transitions) is still an amendment to a frozen contract (unfreeze → review → re-freeze),
so no adapter layer may invent it. See `docs/runbook-settlement.md` (Integration gaps) and ADR-009;
B-1, the two-phase `ChainGateway` gap, is closed by the amendment recorded in
`docs/contracts/settlement-contract-freeze.md` §7.

Every method here is thin on purpose: one unit of work, one repository call, a DTO. No rule lives in
this file — the rules are on the aggregate and the two domain services.
"""

from __future__ import annotations

import re
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.settlement.application.dto import (
    AnchorHashCommand,
    AnchorHashResult,
    CostSummaryQuery,
    CostSummaryView,
    ListOrdersQuery,
    OrderView,
    ReceiptView,
)
from src.settlement.application.services import AnchorHash, CostSummary, GetReceipt, ListOrders
from src.settlement.domain.chain_receipt import ChainReceipt
from src.settlement.domain.ids import OrderId
from src.settlement.domain.ports import ChainGateway
from src.settlement.domain.settlement_order import SettlementOrder
from src.settlement.domain.values import Nullifier
from src.settlement.infrastructure.repositories import (
    SqlChainReceiptRepository,
    SqlSettlementOrderRepository,
    find_nullifier_spend,
    list_orders,
)
from src.shared.application.unit_of_work import session_scope
from src.shared.domain.errors import NotFoundError, ValidationError

__all__ = [
    "AnchorHashService",
    "CostSummaryService",
    "GetOrderService",
    "GetReceiptService",
    "ListOrdersService",
    "ListReceiptsService",
    "NullifierStatusService",
]

#: 32-byte hex, the shape the contract's `anchor(bytes32)` takes.
_BYTES32 = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")


def _order_view(order: SettlementOrder) -> OrderView:
    return OrderView(
        order_id=str(order.id),
        intent_id=str(order.intent_id),
        invoice_id=order.invoice_id,
        status=order.status.value,
        amount_micro_usdc=order.amount.micro_usdc,
        nullifier=order.nullifier.value,
        tx_hash=order.tx_hash,
        chain_id=order.network.chain_id,
    )


def _receipt_view(receipt: ChainReceipt) -> ReceiptView:
    return ReceiptView(
        order_id=str(receipt.order_id),
        tx_hash=receipt.tx_hash,
        block_number=receipt.block_number,
        confirmations=receipt.confirmations,
        status=receipt.status.value,
        gas_used=receipt.gas_used,
        gas_price=receipt.gas_price,
        fee_micro_usdc=receipt.fee_usdc_estimate.micro_usdc,
        is_anchor=receipt.is_anchor,
        revert_reason=receipt.revert_reason,
    )


class GetReceiptService(GetReceipt):
    """Read one order's chain proof (SC-10)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def execute(self, order_id: str) -> ReceiptView:
        async with session_scope(self._session_factory) as session:
            receipt = await SqlChainReceiptRepository(session).find_by_order(OrderId(order_id))
            if receipt is None:
                raise NotFoundError("this order has no chain receipt", order_id=order_id)
            return _receipt_view(receipt)


class GetOrderService:
    """`GET /v1/orders/{id}` — one order's status plus its write-ahead hash (SC-3)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def execute(self, order_id: str) -> OrderView:
        async with session_scope(self._session_factory) as session:
            order = await SqlSettlementOrderRepository(session).find_by_id(OrderId(order_id))
            if order is None:
                raise NotFoundError("no such settlement order", order_id=order_id)
            return _order_view(order)


class ListOrdersService(ListOrders):
    """Read orders for the console, newest first."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def execute(self, query: ListOrdersQuery) -> tuple[OrderView, ...]:
        async with session_scope(self._session_factory) as session:
            orders = await list_orders(session, status=query.status or None, limit=query.limit)
            return tuple(_order_view(order) for order in orders)


class ListReceiptsService:
    """`GET /v1/receipts?day=` — the day's receipts, the rows `CostSummary` sums (SC-10)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def execute(self, day_iso: str) -> tuple[ReceiptView, ...]:
        try:
            day = date.fromisoformat(day_iso)
        except ValueError as exc:
            raise ValidationError("day must be an ISO date (YYYY-MM-DD)", day_iso=day_iso) from exc
        async with session_scope(self._session_factory) as session:
            receipts = await SqlChainReceiptRepository(session).list_for_day(day)
            return tuple(_receipt_view(receipt) for receipt in receipts)


class CostSummaryService(CostSummary):
    """Derive the day's cost from receipts only — never a competing balance (ADR-006, SC-10)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def execute(self, query: CostSummaryQuery) -> CostSummaryView:
        try:
            day = date.fromisoformat(query.day_iso)
        except ValueError as exc:
            raise ValidationError(
                "day must be an ISO date (YYYY-MM-DD)", day_iso=query.day_iso
            ) from exc

        async with session_scope(self._session_factory) as session:
            receipts = await SqlChainReceiptRepository(session).list_for_day(day)
            by_network: dict[str, int] = {}
            orders = SqlSettlementOrderRepository(session)
            for receipt in receipts:
                order = await orders.find_by_id(receipt.order_id)
                # A receipt without an order is impossible by FK-by-convention; if it happens, the
                # cost still belongs to the total, so it is grouped under "unknown" rather than lost.
                key = str(order.network.chain_id) if order else "unknown"
                by_network[key] = by_network.get(key, 0) + receipt.fee_usdc_estimate.micro_usdc
            return CostSummaryView(
                day_iso=day.isoformat(),
                receipt_count=len(receipts),
                total_fee_micro_usdc=sum(
                    receipt.fee_usdc_estimate.micro_usdc for receipt in receipts
                ),
                by_network=by_network,
            )


class AnchorHashService(AnchorHash):
    """Write an evidence/envelope hash on-chain and return the anchor tx (ADR-006).

    The hash is validated here so a malformed evidence hash never reaches the gateway; the gateway port
    owns everything else about the write.
    """

    def __init__(self, gateway: ChainGateway) -> None:
        self._gateway = gateway

    async def execute(self, command: AnchorHashCommand) -> AnchorHashResult:
        raw = command.hash[2:] if command.hash.startswith("0x") else command.hash
        if not _BYTES32.match(raw):
            raise ValidationError("an anchored hash is 32 bytes of hex", anchored_hash=command.hash)
        anchor_tx = await self._gateway.anchor("0x" + raw.lower())
        return AnchorHashResult(anchor_tx=anchor_tx, anchored_hash="0x" + raw.lower())


def nullifier_is_spent(*, marker: str, order_id: str | None) -> tuple[bool, str | None]:
    """Shape the `GET /v1/nullifiers/{value}` answer from what the repository knows.

    Kept as a plain function so the HTTP layer has no domain logic: the endpoint only formats this.
    """
    return (order_id is not None, order_id)


class NullifierStatusService:
    """`GET /v1/nullifiers/{value}` — is this invoice's marker spent, and by which order (SC-5).

    Not one of the six catalog names: it is the read behind the frozen endpoint, and it exists so the
    console/evidence routes never query a table directly.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def execute(self, marker: str) -> tuple[bool, str | None]:
        nullifier = parse_nullifier(marker)
        async with session_scope(self._session_factory) as session:
            order_id = await find_nullifier_spend(session, nullifier)
        return nullifier_is_spent(marker=marker, order_id=order_id)


def parse_nullifier(marker: str) -> Nullifier:
    """Validate a path-supplied nullifier through the value object (422 on a bad shape)."""
    return Nullifier(marker)
