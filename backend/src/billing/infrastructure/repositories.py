"""SQLAlchemy adapters for the ports in `src/billing/domain/repositories.py`.

Canonical: docs/architecture/modules/billing.md#components
Reference: docs/contracts/billing-contract-freeze.md (Persistence contract)

These are the only classes in the module that know a database exists. They **never commit**: the unit
of work in `src/shared/application/unit_of_work.py` owns the transaction (ADR-002), which is what makes
"one application service = one atomic change" checkable.

Both `add` methods flush and translate an integrity error into the domain refusal. That matters beyond
tidiness: the partial unique index is the concurrency backstop for B-1, and a caller must receive
`InvoiceNotPayable`, not a driver-specific `IntegrityError` that the API layer would report as a 500.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.billing.domain.errors import DuplicateInvoice, InvoiceNotPayable
from src.billing.domain.ids import AttemptId, InvoiceId
from src.billing.domain.invoice import Invoice
from src.billing.domain.payment_attempt import PaymentAttempt
from src.billing.domain.repositories import InvoiceRepository, PaymentAttemptRepository
from src.billing.domain.values import InvoiceHash
from src.billing.infrastructure.mappers import (
    attempt_to_domain,
    attempt_to_row,
    events_to_outbox,
    invoice_to_domain,
    invoice_to_row,
)
from src.billing.infrastructure.models import InvoiceRow, OutboxRow, PaymentAttemptRow
from src.shared.domain.event import DomainEvent

__all__ = [
    "OutboxWriter",
    "SqlInvoiceRepository",
    "SqlPaymentAttemptRepository",
    "list_invoices",
]

#: Statuses after which an attempt no longer occupies the invoice (B-1). Mirrors the partial index.
_TERMINAL_STATUSES = ("refused", "settled")


class OutboxWriter:
    """Appends drained events to `billing_outbox` inside the caller's transaction (ADR-003)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, events: tuple[DomainEvent, ...]) -> None:
        for row in events_to_outbox(events):
            self._session.add(OutboxRow(**row))


class SqlInvoiceRepository(InvoiceRepository):
    """`InvoiceRepository` adapter."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, invoice: Invoice) -> None:
        existing = await self.find_by_hash(invoice.hash)
        if existing is not None:
            raise DuplicateInvoice(invoice_hash=invoice.hash.value)
        self._session.add(invoice_to_row(invoice))
        try:
            await self._session.flush()
        except IntegrityError as exc:  # the unique hash index raced us (B-3)
            raise DuplicateInvoice(invoice_hash=invoice.hash.value) from exc
        invoice.version = 1

    async def find_by_id(self, id_: InvoiceId) -> Invoice | None:
        row = await self._session.get(InvoiceRow, str(id_))
        return invoice_to_domain(row) if row else None

    async def find_by_hash(self, hash_: InvoiceHash) -> Invoice | None:
        result = await self._session.execute(
            select(InvoiceRow).where(InvoiceRow.invoice_hash == hash_.value)
        )
        row = result.scalar_one_or_none()
        return invoice_to_domain(row) if row else None

    async def save(self, invoice: Invoice) -> None:
        row = await self._session.get(InvoiceRow, str(invoice.id))
        if row is None:
            self._session.add(invoice_to_row(invoice))
            invoice.version = 1
            return
        row.status = invoice.status.value
        row.version = row.version + 1
        invoice.version = row.version


class SqlPaymentAttemptRepository(PaymentAttemptRepository):
    """`PaymentAttemptRepository` adapter."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, attempt: PaymentAttempt) -> None:
        active = await self.find_active_for_invoice(attempt.invoice_id)
        if active is not None:
            raise InvoiceNotPayable(str(attempt.invoice_id), active.status.value)
        self._session.add(attempt_to_row(attempt))
        try:
            await self._session.flush()
        except IntegrityError as exc:  # the partial unique index raced us (B-1)
            raise InvoiceNotPayable(str(attempt.invoice_id), "in_flight") from exc
        attempt.version = 1

    async def find_by_id(self, id_: AttemptId) -> PaymentAttempt | None:
        row = await self._session.get(PaymentAttemptRow, str(id_))
        return attempt_to_domain(row) if row else None

    async def find_active_for_invoice(self, invoice_id: InvoiceId) -> PaymentAttempt | None:
        result = await self._session.execute(
            select(PaymentAttemptRow)
            .where(
                PaymentAttemptRow.invoice_id == str(invoice_id),
                PaymentAttemptRow.status.not_in(_TERMINAL_STATUSES),
            )
            .order_by(PaymentAttemptRow.created_at.desc())
        )
        row = result.scalars().first()
        return attempt_to_domain(row) if row else None

    async def save(self, attempt: PaymentAttempt) -> None:
        row = await self._session.get(PaymentAttemptRow, str(attempt.id))
        if row is None:
            self._session.add(attempt_to_row(attempt))
            attempt.version = 1
            return
        row.status = attempt.status.value
        row.version = row.version + 1
        attempt.version = row.version


async def list_invoices(
    session: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> list[Invoice]:
    """Read-model query for `GET /v1/invoices`.

    A read model, not an aggregate load: it deliberately bypasses the repository port because listing
    is not a domain decision. `cursor` is the last id of the previous page (ids sort lexically).
    """
    statement = select(InvoiceRow).order_by(InvoiceRow.created_at, InvoiceRow.id).limit(limit)
    if status:
        statement = statement.where(InvoiceRow.status == status)
    if cursor:
        statement = statement.where(InvoiceRow.id > cursor)
    result = await session.execute(statement)
    return [invoice_to_domain(row) for row in result.scalars().all()]
