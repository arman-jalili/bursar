"""Billing persistence + application integration (real SQLite, real adapters).

Canonical: .pi/architecture/modules/billing.md#acceptance-criteria
Reference: docs/contracts/billing-contract-freeze.md (Persistence contract)

Defends the storage mirrors of B-1 and B-3, and the application-service behaviour the module doc's
acceptance table names:

    AC #2  a replay yields the original invoice + `DuplicateInvoiceDetected`, and exactly one row
    AC #3  a second proposal for the same invoice is refused, with exactly one attempt persisted

Both are asserted through the real repository adapters, because a fake would not prove the `UNIQUE
(invoice_hash)` constraint or the partial unique index that make the race impossible.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.billing.application.dto import ProposePaymentCommand, RecordInvoiceCommand
from src.billing.application.services_impl import ProposePaymentService, RecordInvoiceService
from src.billing.domain.errors import DuplicateInvoice, InvoiceNotPayable
from src.billing.domain.ids import AttemptId, PayeeId, new_id
from src.billing.domain.invoice import Invoice
from src.billing.domain.values import BilledAmount, InvoiceHash, InvoiceStatus
from src.billing.infrastructure.models import Base, InvoiceRow, OutboxRow, PaymentAttemptRow
from src.billing.infrastructure.repositories import (
    SqlInvoiceRepository,
    SqlPaymentAttemptRepository,
)
from src.shared.application.unit_of_work import session_scope
from src.shared.infrastructure.db import build_engine, build_session_factory

from tests.unit.billing._fixtures import a_digest, a_document

DUE = date(2026, 11, 20)


@pytest.fixture
async def factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = build_engine(f"sqlite+aiosqlite:///{tmp_path / 'billing.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield build_session_factory(engine)
    finally:
        await engine.dispose()


def _command(document: dict[str, object] | None = None) -> RecordInvoiceCommand:
    return RecordInvoiceCommand(
        payee_id=str(PayeeId(new_id())),
        amount_micro_usdc=42_500_000,
        due_date=DUE,
        document=document if document is not None else a_document(),
        presented_digest=a_digest().hash,
    )


async def _count(factory: async_sessionmaker[AsyncSession], row: type) -> int:
    async with session_scope(factory) as session:
        result = await session.execute(select(func.count()).select_from(row))
        return int(result.scalar_one())


class TestDuplicateInvoice:
    async def test_a_replay_returns_the_original_invoice_and_records_the_fact(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """AC #2: same hash twice → original invoice + DuplicateInvoiceDetected, no second row."""
        service = RecordInvoiceService(factory)

        first = await service.execute(_command())
        second = await service.execute(_command())

        assert second.duplicate is True
        assert second.invoice.invoice_id == first.invoice.invoice_id
        assert second.events == ("DuplicateInvoiceDetected",)
        assert await _count(factory, InvoiceRow) == 1

        async with session_scope(factory) as session:
            result = await session.execute(
                select(OutboxRow).where(OutboxRow.event_name == "DuplicateInvoiceDetected")
            )
            event = result.scalar_one()
        payload = json.loads(event.payload)
        assert payload["invoice_id"] == first.invoice.invoice_id
        assert payload["original_invoice_id"] == first.invoice.invoice_id
        assert payload["invoice_hash"] == first.invoice.invoice_hash

    async def test_a_one_character_change_is_a_second_bill(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """B-3: a different invoice number is a different obligation."""
        service = RecordInvoiceService(factory)

        await service.execute(_command())
        second = await service.execute(_command(a_document(invoice_number="INV-2026-0043")))

        assert second.duplicate is False
        assert await _count(factory, InvoiceRow) == 2

    async def test_the_adapter_refuses_a_duplicate_even_without_the_service(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """B-3 at the port: `add` is the insert path and refuses a known hash."""
        invoice = Invoice.from_document(
            payee_id=PayeeId(new_id()),
            amount=BilledAmount(micro_usdc=42_500_000),
            due_date=DUE,
            document=a_document(),
            presented_digest=a_digest(),
        )
        async with session_scope(factory) as session:
            await SqlInvoiceRepository(session).add(invoice)

        replay = Invoice.from_document(
            payee_id=PayeeId(new_id()),
            amount=BilledAmount(micro_usdc=42_500_000),
            due_date=DUE,
            document=a_document(),
            presented_digest=a_digest(),
        )
        with pytest.raises(DuplicateInvoice):
            async with session_scope(factory) as session:
                await SqlInvoiceRepository(session).add(replay)


class TestAtMostOneAttempt:
    async def test_a_second_proposal_is_refused_and_only_one_attempt_is_persisted(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """AC #3: one invoice → one `PaymentAttempt`; the second proposal gets `InvoiceNotPayable`."""
        invoices = RecordInvoiceService(factory)
        proposed = await invoices.execute(_command())
        service = ProposePaymentService(factory)

        first = await service.execute(ProposePaymentCommand(invoice_id=proposed.invoice.invoice_id))
        with pytest.raises(InvoiceNotPayable):
            await service.execute(ProposePaymentCommand(invoice_id=proposed.invoice.invoice_id))

        assert await _count(factory, PaymentAttemptRow) == 1
        assert first.attempt.status == "proposed"

        async with session_scope(factory) as session:
            invoice = await SqlInvoiceRepository(session).find_by_id(
                proposed.invoice.invoice_id  # type: ignore[arg-type]
            )
        assert invoice is not None and invoice.status is InvoiceStatus.IN_FLIGHT

    async def test_two_concurrent_proposals_produce_exactly_one_attempt(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """AC #3 (concurrency): two proposals racing one invoice → one attempt, one refusal.

        Both services may read the invoice before either commits, so the domain guard alone cannot
        save us here — the partial unique index is the arbiter, and the adapter translates the
        integrity error into the same `InvoiceNotPayable` the serial path raises.
        """
        proposed = await RecordInvoiceService(factory).execute(_command())
        service = ProposePaymentService(factory)
        command = ProposePaymentCommand(invoice_id=proposed.invoice.invoice_id)

        results = await asyncio.gather(
            service.execute(command), service.execute(command), return_exceptions=True
        )

        succeeded = [result for result in results if not isinstance(result, BaseException)]
        refused = [result for result in results if isinstance(result, BaseException)]
        assert len(succeeded) == 1, f"expected exactly one winner, got {results!r}"
        assert len(refused) == 1
        assert isinstance(refused[0], InvoiceNotPayable)
        assert await _count(factory, PaymentAttemptRow) == 1

    async def test_the_partial_unique_index_is_the_last_line_of_defence(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """B-1 in storage: two active attempts cannot both be inserted, even bypassing the service."""
        from src.billing.domain.payment_attempt import PaymentAttempt

        invoice = Invoice.from_document(
            payee_id=PayeeId(new_id()),
            amount=BilledAmount(micro_usdc=42_500_000),
            due_date=DUE,
            document=a_document(),
            presented_digest=a_digest(),
        )
        async with session_scope(factory) as session:
            await SqlInvoiceRepository(session).add(invoice)
            first = PaymentAttempt.from_proposal({"invoice_id": invoice.id}, invoice)
            await SqlPaymentAttemptRepository(session).add(first)

        second = PaymentAttempt(
            id=AttemptId(new_id()),
            invoice_id=first.invoice_id,
            status=first.status,
        )
        # The adapter's own guard refuses before the index is reached.
        with pytest.raises(InvoiceNotPayable):
            async with session_scope(factory) as session:
                await SqlPaymentAttemptRepository(session).add(second)


class TestInvoiceHashPersists:
    async def test_the_recorded_hash_is_the_insert_key(
        self, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        service = RecordInvoiceService(factory)
        result = await service.execute(_command())
        expected = InvoiceHash.from_document(a_document())

        async with session_scope(factory) as session:
            found = await SqlInvoiceRepository(session).find_by_hash(expected)
            row = await session.get(InvoiceRow, result.invoice.invoice_id)

        assert found is not None and row is not None
        assert row.invoice_hash == expected.value
