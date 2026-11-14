"""Read models for the payer's bill list — household language, no rules.

The console's upstream contract names one bill row per invoice. The payee display name is read from
Mandate's table; the demo runs both contexts against one SQLite file, so this is a real read, not a
fixture.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.authority.infrastructure.models import DeterminationRow, PaymentIntentRow
from src.billing.infrastructure.models import InvoiceRow
from src.mandate.infrastructure.models import PayeeRow
from src.settlement.infrastructure.models import SettlementOrderRow
from src.shared.application.unit_of_work import session_scope

__all__ = ["BillingQueries"]

_STATUS = {
    "received": ("RECEIVED", "Bill received"),
    "in_flight": ("IN_FLIGHT", "Payment in progress"),
    "settled": ("SETTLED", "Paid"),
    "refused": ("REFUSED", "Refused"),
}

_REFUSAL_COPY = {
    "payee_quarantined": "The payee's bank details changed. Nothing was sent.",
    "digest_mismatch": "The payee's bank details changed. Nothing was sent.",
    "payee_frozen": "The payee is frozen. Nothing was sent.",
    "cap_exceeded": "This would pass today's cap. Nothing was sent.",
    "duplicate_invoice": "This invoice was already paid. Nothing was sent.",
}
_ESCALATE_COPY = "A new payee above your line. Waiting for you."


class BillingQueries:
    """The payer's bills, newest first."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def payer_bills(self) -> list[dict[str, object]]:
        async with session_scope(self._factory) as session:
            result = await session.execute(
                select(InvoiceRow, PayeeRow.name)
                .join(PayeeRow, PayeeRow.id == InvoiceRow.payee_id)
                .order_by(InvoiceRow.created_at.desc())
            )
            rows: list[dict[str, object]] = []
            for invoice, payee_name in result.all():
                status, plain = _STATUS.get(
                    invoice.status, ("IN_FLIGHT", "Payment in progress")
                )
                refusal: str | None = None
                reason_codes: list[str] = []
                tx_hash: str | None = None
                settled_at: str | None = None

                # A broadcast order means the money moved (the chain accepted the bytes). The
                # finality poller is not wired yet, so `submitted` is the demo's paid state; the
                # transaction hash is the receipt's identity either way.
                order = await session.scalar(
                    select(SettlementOrderRow)
                    .where(SettlementOrderRow.invoice_id == invoice.id)
                    .order_by(SettlementOrderRow.created_at.desc())
                    .limit(1)
                )
                if order is not None and order.tx_hash and order.status in (
                    "submitted",
                    "pending",
                    "confirmed",
                ):
                    status, plain = "SETTLED", "Paid"
                    tx_hash = order.tx_hash
                    settled_at = (
                        order.updated_at.isoformat() if order.updated_at is not None else None
                    )

                # The determination is the real story for a proposed bill: a denied attempt is a
                # refusal the payer should see, even though the invoice row itself stays received.
                intent_id = await session.scalar(
                    select(PaymentIntentRow.id)
                    .where(PaymentIntentRow.invoice_id == invoice.id)
                    .order_by(PaymentIntentRow.created_at.desc())
                    .limit(1)
                )
                if intent_id is not None:
                    determination = await session.scalar(
                        select(DeterminationRow).where(DeterminationRow.intent_id == intent_id)
                    )
                    if (
                        determination is not None
                        and invoice.status != "settled"
                        and status != "SETTLED"
                    ):
                        if determination.verdict == "deny":
                            status, plain = "REFUSED", "Refused"
                            codes = [
                                code
                                for code in (determination.reason_codes or "").split(",")
                                if code
                            ]
                            reason_codes = [code.upper() for code in codes]
                            refusal = next(
                                (_REFUSAL_COPY.get(code) for code in codes if code in _REFUSAL_COPY),
                                "The payment was refused. Nothing was sent.",
                            )
                        elif determination.verdict == "escalate":
                            status, plain = "IN_FLIGHT", "Waiting for you"
                            refusal = _ESCALATE_COPY
                        else:
                            status, plain = "IN_FLIGHT", "Being paid"

                if status == "SETTLED" and settled_at is None:
                    settled_at = datetime.now(UTC).isoformat()
                rows.append(
                    {
                        "invoice_id": invoice.id,
                        "payee_name": payee_name,
                        "amount_usdc": f"{invoice.amount_micro_usdc / 1_000_000:.2f}",
                        "status": status,
                        "status_plain": plain,
                        "settled_at": settled_at,
                        "tx_hash": tx_hash,
                        "payout_simulated": status == "SETTLED",
                        "payout_label": (
                            "bank transfer simulated in this demo" if status == "SETTLED" else None
                        ),
                        "reason_codes": reason_codes,
                        "refusal_reason": refusal,
                    }
                )
            return rows
