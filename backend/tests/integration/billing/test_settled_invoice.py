"""AC #5 — a settled invoice is closed and accepts no further attempts (scenario 6).

Canonical: docs/architecture/modules/billing.md#acceptance-criteria
Reference: docs/contracts/billing-contract-freeze.md (B-2)

Drives the inbound `SettlementConfirmed` path through the application layer, then tries to propose
again. Also proves at-least-once delivery is idempotent: a replayed settlement returns the original
invoice and writes no second `InvoiceSettled` fact.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.billing.application.dto import (
    ProposePaymentCommand,
    SettleInvoiceCommand,
)
from src.billing.application.services_impl import (
    ProposePaymentService,
    RecordInvoiceService,
    SettleInvoiceService,
)
from src.billing.domain.errors import InvoiceAlreadySettled
from src.billing.infrastructure.models import OutboxRow, PaymentAttemptRow

from tests.integration.billing.conftest import record_command


async def _count(factory: async_sessionmaker[AsyncSession], row: type) -> int:
    async with factory() as session:
        result = await session.execute(select(func.count()).select_from(row))
        return int(result.scalar_one())


async def _settled(factory: async_sessionmaker[AsyncSession]) -> tuple[str, str]:
    recorded = await RecordInvoiceService(factory).execute(record_command())
    invoice_id = recorded.invoice.invoice_id
    proposed = await ProposePaymentService(factory).execute(
        ProposePaymentCommand(invoice_id=invoice_id)
    )
    await SettleInvoiceService(factory).execute(
        SettleInvoiceCommand(invoice_id=invoice_id, tx_hash="0xabc", event_id="evt-1")
    )
    return invoice_id, proposed.attempt.attempt_id


class TestSettledInvoice:
    async def test_settlement_closes_the_invoice_and_carries_the_transaction_hash(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """B-2: the invoice lands in SETTLED and `InvoiceSettled` carries the on-chain proof."""
        invoice_id, _ = await _settled(factory)

        async with factory() as session:
            result = await session.execute(
                select(OutboxRow).where(OutboxRow.event_name == "InvoiceSettled")
            )
            payload = json.loads(result.scalar_one().payload)

        assert payload["invoice_id"] == invoice_id
        assert payload["tx_hash"] == "0xabc"

    async def test_a_settled_invoice_refuses_a_new_attempt_and_writes_no_row(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """AC #5: the proposal is refused and no attempt row is created."""
        invoice_id, _ = await _settled(factory)
        before = await _count(factory, PaymentAttemptRow)

        with pytest.raises(InvoiceAlreadySettled):
            await ProposePaymentService(factory).execute(
                ProposePaymentCommand(invoice_id=invoice_id)
            )

        assert await _count(factory, PaymentAttemptRow) == before == 1

    async def test_a_replayed_settlement_is_idempotent(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """ADR-003 at-least-once: the same delivery twice is one fact."""
        invoice_id, _ = await _settled(factory)
        before = await _count(factory, OutboxRow)

        replay = await SettleInvoiceService(factory).execute(
            SettleInvoiceCommand(invoice_id=invoice_id, tx_hash="0xabc", event_id="evt-1")
        )

        assert replay.duplicate is True
        assert replay.events == ()
        assert await _count(factory, OutboxRow) == before
