"""Concrete Billing application services — one unit of work each (ADR-002).

Canonical: .pi/architecture/modules/billing.md#application-services
Reference: docs/contracts/billing-contract-freeze.md §2.7

The shape of every method is the same, deliberately:

1. open exactly one `session_scope`,
2. load the aggregate through its port,
3. call **one** intention method on the aggregate (the rules live there),
4. save, append drained events to `billing_outbox` in the same transaction, return a DTO.

No business rule appears here. If a rule needs to change, it belongs on `Invoice` or `PaymentAttempt`
— that is what keeps the use cases thin and testable without a server.

`RecordInvoiceService` has one non-obvious branch: a replay is **not** an error on the wire. The hash
already identifies a bill, so the caller receives that original invoice plus a
`DuplicateInvoiceDetected` fact (B-3). Raising instead would deny the caller the identifier it needs.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.billing.application.dto import (
    AttemptView,
    InvoiceView,
    ProposePaymentCommand,
    ProposePaymentResult,
    RecordInvoiceCommand,
    RecordInvoiceResult,
)
from src.billing.application.services import ProposePayment, RecordInvoice
from src.billing.domain.events import DuplicateInvoiceDetected
from src.billing.domain.ids import AttemptId, InvoiceId, PayeeId
from src.billing.domain.invoice import Invoice
from src.billing.domain.payment_attempt import PaymentAttempt
from src.billing.domain.ports import DigestReviewPort
from src.billing.domain.values import BilledAmount, InvoiceHash
from src.billing.infrastructure.repositories import (
    OutboxWriter,
    SqlInvoiceRepository,
    SqlPaymentAttemptRepository,
    list_invoices,
)
from src.mandate.domain.values import BankDigest
from src.shared.application.unit_of_work import session_scope
from src.shared.domain.errors import NotFoundError

__all__ = [
    "GetAttemptService",
    "GetInvoiceService",
    "ListInvoicesService",
    "ProposePaymentService",
    "RecordInvoiceService",
]


def _invoice_view(invoice: Invoice) -> InvoiceView:
    return InvoiceView(
        invoice_id=str(invoice.id),
        payee_id=str(invoice.payee_id),
        invoice_hash=invoice.hash.value,
        amount_micro_usdc=invoice.amount.micro_usdc,
        due_date_iso=invoice.due_date.isoformat(),
        presented_digest=invoice.presented_digest.hash,
        status=invoice.status.value,
    )


def _attempt_view(attempt: PaymentAttempt) -> AttemptView:
    return AttemptView(
        attempt_id=str(attempt.id),
        invoice_id=str(attempt.invoice_id),
        status=attempt.status.value,
    )


class RecordInvoiceService(RecordInvoice):
    """FR-007 — register a bill, keep the presented digest, refuse/absorb a replay (B-3, B-4)."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        digest_review: DigestReviewPort | None = None,
    ) -> None:
        self._factory = session_factory
        self._digest_review = digest_review

    async def execute(self, command: RecordInvoiceCommand) -> RecordInvoiceResult:
        invoice_hash = InvoiceHash.from_document(command.document)
        presented = BankDigest(hash=command.presented_digest)
        amount = BilledAmount(micro_usdc=command.amount_micro_usdc)

        async with session_scope(self._factory) as session:
            repository = SqlInvoiceRepository(session)
            existing = await repository.find_by_hash(invoice_hash)
            if existing is not None:
                # B-3: a replay returns the bill that already exists, and the fact is recorded so the
                # replayed demand is visible in the audit trail. No second row is written.
                event = DuplicateInvoiceDetected(
                    invoice_id=str(existing.id),
                    invoice_hash=existing.hash.value,
                    original_invoice_id=str(existing.id),
                )
                await OutboxWriter(session).append((event,))
                return RecordInvoiceResult(
                    invoice=_invoice_view(existing),
                    duplicate=True,
                    events=(event.event_name,),
                )

            invoice = Invoice.from_document(
                payee_id=PayeeId(command.payee_id),
                amount=amount,
                due_date=command.due_date,
                document=command.document,
                presented_digest=presented,
            )
            if self._digest_review is not None:
                # B-4: report the presented digest; Mandate quarantines on mismatch. The review is a
                # view, never a routing decision, and a mismatch is not raised here.
                await self._digest_review.review(
                    invoice_id=str(invoice.id),
                    payee_id=command.payee_id,
                    presented_digest=presented,
                )
            await repository.add(invoice)
            events = invoice.pull_events()
            await OutboxWriter(session).append(events)
            return RecordInvoiceResult(
                invoice=_invoice_view(invoice),
                events=tuple(event.event_name for event in events),
            )


class ProposePaymentService(ProposePayment):
    """FR-009 — translate an untrusted proposal into an attempt (B-1, B-2, B-5, B-6)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def execute(self, command: ProposePaymentCommand) -> ProposePaymentResult:
        async with session_scope(self._factory) as session:
            invoices = SqlInvoiceRepository(session)
            attempts = SqlPaymentAttemptRepository(session)

            invoice = await invoices.find_by_id(InvoiceId(command.invoice_id))
            if invoice is None:
                raise NotFoundError("No invoice with that id.", invoice_id=command.invoice_id)

            payload: dict[str, object] = {"invoice_id": command.invoice_id}
            if command.proposed_amount_micro_usdc is not None:
                payload["proposed_amount_micro_usdc"] = command.proposed_amount_micro_usdc

            attempt = PaymentAttempt.from_proposal(payload, invoice)
            await attempts.add(attempt)
            # The invoice status is part of B-1: IN_FLIGHT is what a later proposal reads.
            await invoices.save(invoice)
            events = attempt.pull_events()
            await OutboxWriter(session).append(events)
            return ProposePaymentResult(
                attempt=_attempt_view(attempt),
                events=tuple(event.event_name for event in events),
            )


class ListInvoicesService:
    """Read model behind `GET /v1/invoices` (module doc: below the catalog)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def execute(
        self, *, status: str | None = None, cursor: str | None = None, limit: int = 50
    ) -> list[InvoiceView]:
        async with session_scope(self._factory) as session:
            invoices = await list_invoices(
                session, status=status, cursor=cursor, limit=max(1, min(limit, 200))
            )
            return [_invoice_view(invoice) for invoice in invoices]


class GetInvoiceService:
    """Read one invoice by id (module doc: below the catalog)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def execute(self, invoice_id: str) -> InvoiceView:
        async with session_scope(self._factory) as session:
            invoice = await SqlInvoiceRepository(session).find_by_id(InvoiceId(invoice_id))
            if invoice is None:
                raise NotFoundError("No invoice with that id.", invoice_id=invoice_id)
            return _invoice_view(invoice)


class GetAttemptService:
    """Read one attempt by id (module doc: below the catalog)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def execute(self, attempt_id: str) -> AttemptView:
        async with session_scope(self._factory) as session:
            attempt = await SqlPaymentAttemptRepository(session).find_by_id(AttemptId(attempt_id))
            if attempt is None:
                raise NotFoundError("No attempt with that id.", attempt_id=attempt_id)
            return _attempt_view(attempt)
