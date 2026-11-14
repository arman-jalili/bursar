"""Row ⇄ aggregate translation — the seam that keeps ORM types out of the model.

Canonical: docs/architecture/modules/billing.md#components
Reference: docs/architecture/decisions/ADR-002-data-storage-strategy.md

Two rules, the same ones Mandate uses:

1. **Rehydration is not a state change.** A stored aggregate must not re-emit its creation events, so
   the mappers drain them after rebuilding the object.
2. **Value objects are reconstructed through their validation**, so a corrupt row fails loudly at the
   boundary instead of becoming a silently-zero amount.
"""

from __future__ import annotations

import dataclasses
import json

from src.billing.domain.ids import AttemptId, InvoiceId, PayeeId
from src.billing.domain.invoice import Invoice
from src.billing.domain.payment_attempt import PaymentAttempt
from src.billing.domain.values import AttemptStatus, BilledAmount, InvoiceHash, InvoiceStatus
from src.billing.infrastructure.models import InvoiceRow, PaymentAttemptRow
from src.mandate.domain.values import BankDigest
from src.shared.domain.event import DomainEvent

__all__ = [
    "attempt_to_domain",
    "attempt_to_row",
    "events_to_outbox",
    "invoice_to_domain",
    "invoice_to_row",
]


def _settle(aggregate: object) -> None:
    """Rehydration is not a state change: drop the events the factory recorded."""
    pull = getattr(aggregate, "pull_events", None)
    if callable(pull):
        pull()


def invoice_to_domain(row: InvoiceRow) -> Invoice:
    invoice = Invoice(
        id=InvoiceId(row.id),
        payee_id=PayeeId(row.payee_id),
        hash=InvoiceHash(value=row.invoice_hash),
        amount=BilledAmount(micro_usdc=row.amount_micro_usdc),
        due_date=row.due_date,
        presented_digest=BankDigest(hash=row.presented_digest),
        status=InvoiceStatus(row.status),
        version=row.version,
    )
    _settle(invoice)
    return invoice


def invoice_to_row(invoice: Invoice) -> InvoiceRow:
    return InvoiceRow(
        id=str(invoice.id),
        payee_id=str(invoice.payee_id),
        invoice_hash=invoice.hash.value,
        amount_micro_usdc=invoice.amount.micro_usdc,
        due_date=invoice.due_date,
        presented_digest=invoice.presented_digest.hash,
        status=invoice.status.value,
        version=invoice.version,
    )


def attempt_to_domain(row: PaymentAttemptRow) -> PaymentAttempt:
    attempt = PaymentAttempt(
        id=AttemptId(row.id),
        invoice_id=InvoiceId(row.invoice_id),
        status=AttemptStatus(row.status),
        version=row.version,
    )
    _settle(attempt)
    return attempt


def attempt_to_row(attempt: PaymentAttempt) -> PaymentAttemptRow:
    return PaymentAttemptRow(
        id=str(attempt.id),
        invoice_id=str(attempt.invoice_id),
        status=attempt.status.value,
        version=attempt.version,
    )


def events_to_outbox(events: tuple[DomainEvent, ...]) -> list[dict[str, object]]:
    """Serialise drained events for `billing_outbox` (ADR-003)."""
    rows: list[dict[str, object]] = []
    for event in events:
        payload = {f.name: getattr(event, f.name) for f in dataclasses.fields(event)}
        payload = {k: v.isoformat() if hasattr(v, "isoformat") else v for k, v in payload.items()}
        rows.append(
            {
                "event_id": event.event_id,
                "event_name": event.event_name,
                "aggregate_id": event.aggregate_id,
                "correlation_id": event.correlation_id,
                "payload": json.dumps(payload, sort_keys=True, default=str),
                "occurred_at": event.occurred_at,
            }
        )
    return rows
