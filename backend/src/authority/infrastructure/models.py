"""Authority tables — SQLAlchemy 2.0 models. Never imported by `domain/`.

Canonical: .pi/architecture/modules/authority.md#components
Reference: .pi/architecture/decisions/ADR-002-data-storage-strategy.md

Design notes, each one an invariant made structural:

* **Amounts are `INTEGER` micro-USDC** (ADR-002). A float column would let a rounded amount pass a cap
  comparison it should fail.
* **`authority_cap_ledger` has one row per day** (A-12): the day is the primary key, so a rollover is a
  new row rather than a reset of an old one, and `committed` can never be un-spent by an update that
  forgets which day it belonged to.
* **`authority_reservations.status` is checked at the storage layer** with a partial index, so "resolved
  exactly once" (A-10) has a database-side guard in addition to the conditional update the adapter runs.
* **Determinations have no `updated_at`** and no update path: an append-only verdict table (A-7).
* **Approvals store the recovered signer and the signed digest** — not the signature alone — so the
  binding is auditable after the fact without re-running recovery (A-13).
* **Routing data is never duplicated here beyond the intent's snapshot**, which is copied from Mandate's
  verified record at issue time (A-2) and sealed into the intent the owner signs.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

__all__ = [
    "ApprovalRow",
    "Base",
    "CapLedgerRow",
    "DeterminationRow",
    "OutboxRow",
    "PaymentIntentRow",
    "ReservationRow",
]


class Base(DeclarativeBase):
    """Declarative base for the Authority schema (`authority_*` tables)."""


class PaymentIntentRow(Base):
    """The immutable intent (A-1). No `updated_at` because an issued intent never changes."""

    __tablename__ = "authority_payment_intents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    invoice_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payee_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Mandate's verified address, copied at issue time (A-2) — provenance, not caller input.
    payee_address: Mapped[str] = mapped_column(String(42), nullable=False)
    amount_micro_usdc: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Mandate's verified digest, copied at issue time (A-2).
    bank_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    is_new_payee: Mapped[bool] = mapped_column(nullable=False, default=False)
    requires_owner_signature: Mapped[bool] = mapped_column(nullable=False, default=False)
    constitution_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_authority_payment_intents_payee", "payee_id"),
        Index("ix_authority_payment_intents_invoice", "invoice_id"),
    )


class DeterminationRow(Base):
    """Append-only verdict (A-5, A-7). One determination per intent, never revised."""

    __tablename__ = "authority_determinations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    intent_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Comma-separated closed-set codes; a DENY has at least one (A-5), enforced by the domain.
    reason_codes: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    constitution_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payee_status_read: Mapped[str] = mapped_column(String(20), nullable=False)
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ledger_snapshot_micro_usdc: Mapped[int] = mapped_column(Integer, nullable=False)


class CapLedgerRow(Base):
    """One ledger row per day (A-9 … A-12). `day` is the key, so a rollover is a new row."""

    __tablename__ = "authority_cap_ledger"

    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    cap_micro_usdc: Mapped[int] = mapped_column(Integer, nullable=False)
    committed_micro_usdc: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_micro_usdc: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        # A-9 as a real database guard, not just an adapter convention: a row cannot hold more than
        # its cap even if a future code path forgets the conditional UPDATE.
        CheckConstraint(
            "committed_micro_usdc + reserved_micro_usdc <= cap_micro_usdc",
            name="ck_authority_cap_ledger_within_cap",
        ),
    )


class ReservationRow(Base):
    """A hold with a one-way lifecycle (A-10)."""

    __tablename__ = "authority_reservations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    intent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_micro_usdc: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Frozen at hold time (A-12): a late settlement still lands in the day it reserved against.
    day: Mapped[str] = mapped_column(String(10), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="held")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("intent_id", name="uq_authority_reservation_intent"),
        Index("ix_authority_reservations_day", "day"),
        Index("ix_authority_reservations_status", "status"),
    )


class ApprovalRow(Base):
    """A signature request bound to one intent, single-use and expiring (A-13 … A-15)."""

    __tablename__ = "authority_approvals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    intent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    typed_data_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Proof artifact, present only after verification (A-13/A-15).
    signature_hex: Mapped[str | None] = mapped_column(String(200), nullable=True)
    signer: Mapped[str | None] = mapped_column(String(42), nullable=True)
    signed_digest: Mapped[str | None] = mapped_column(String(66), nullable=True)

    __table_args__ = (
        Index("ix_authority_approvals_pending", "consumed_at", "expires_at"),
    )


class OutboxRow(Base):
    """Transactional outbox (ADR-003): events are written with the state they describe."""

    __tablename__ = "authority_outbox"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_name: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[str] = mapped_column(String, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_authority_outbox_unpublished", "published_at"),)
