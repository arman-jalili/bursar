"""Read models the console uses for a bill's chain receipt.

Only facts the chain layer wrote: the order's transaction hash and the receipt's observation time.
No amount is recomputed and no verdict is inferred.
"""

from __future__ import annotations

from datetime import UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.settlement.infrastructure.models import (
    SettlementOrderRow,
    SettlementReceiptRow,
)
from src.shared.application.unit_of_work import session_scope

__all__ = ["InvoiceReceiptQuery"]


class InvoiceReceiptQuery:
    """Find the chain movement for one invoice, if one was recorded."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def for_invoice(self, invoice_id: str) -> dict[str, object] | None:
        async with session_scope(self._factory) as session:
            order = await session.scalar(
                select(SettlementOrderRow)
                .where(SettlementOrderRow.invoice_id == invoice_id)
                .order_by(SettlementOrderRow.created_at.desc())
                .limit(1)
            )
            if order is None or order.tx_hash is None:
                return None
            receipt = await session.scalar(
                select(SettlementReceiptRow)
                .where(SettlementReceiptRow.order_id == order.id)
                .order_by(SettlementReceiptRow.observed_at.desc())
                .limit(1)
            )
            observed = receipt.observed_at if receipt is not None else order.updated_at
            if observed is not None and observed.tzinfo is None:
                observed = observed.replace(tzinfo=UTC)
            return {
                "invoice_id": invoice_id,
                "tx_hash": order.tx_hash,
                "settled_at": observed.isoformat() if observed is not None else None,
            }
