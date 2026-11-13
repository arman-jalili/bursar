"""Billing tables — SQLAlchemy 2.0 models. Never imported by `domain/` or `application/`.

Canonical: .pi/architecture/modules/billing.md#components
Reference: docs/contracts/billing-contract-freeze.md (Persistence contract)

The two storage mirrors of the domain invariants live here, because a guarantee the database does not
enforce is a guarantee a concurrent request can forget:

* `uq_billing_invoices_hash` — one row per invoice hash, the local duplicate lock (B-3). Without it a
  replay could enter twice between the service's read and its insert.
* `uq_billing_attempts_one_active` — a **partial** unique index on `invoice_id` for every non-terminal
  status (B-1). Two concurrent proposals cannot both insert an active attempt; the second gets a domain
  refusal from the adapter instead of a double payment.

Routing details are deliberately absent (B-4): only the presented digest is stored, so a database leak
cannot redirect a payment.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

__all__ = ["Base", "InvoiceRow", "OutboxRow", "PaymentAttemptRow"]


class Base(DeclarativeBase):
    """Declarative base for the Billing schema (`billing_*` tables)."""


class InvoiceRow(Base):
    __tablename__ = "billing_invoices"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payee_id: Mapped[str] = mapped_column(String(64), nullable=False)
    invoice_hash: Mapped[str] = mapped_column(Text, nullable=False)
    amount_micro_usdc: Mapped[int] = mapped_column(Integer, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    presented_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # B-3 at the storage layer: the hash is the insert key.
        UniqueConstraint("invoice_hash", name="uq_billing_invoices_hash"),
        Index("ix_billing_invoices_status", "status"),
        Index("ix_billing_invoices_payee", "payee_id"),
    )


class PaymentAttemptRow(Base):
    __tablename__ = "billing_attempts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    invoice_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("billing_invoices.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # B-1 at the storage layer: at most one non-terminal attempt per invoice. SQLite (and
        # PostgreSQL) support partial unique indexes; the predicate states "terminal" explicitly so a
        # new status is active unless it is listed here.
        Index(
            "uq_billing_attempts_one_active",
            "invoice_id",
            unique=True,
            sqlite_where=text("status NOT IN ('refused', 'settled')"),
        ),
        Index("ix_billing_attempts_invoice", "invoice_id"),
    )


class OutboxRow(Base):
    """Transactional outbox (ADR-003): events are written in the same transaction as the state."""

    __tablename__ = "billing_outbox"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_name: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_billing_outbox_unpublished", "published_at"),)
