"""Settlement tables — SQLAlchemy 2.0 models. Never imported by `domain/` or `application/`.

Canonical: docs/architecture/modules/settlement.md#repository-interfaces-owned-by-domain
Reference: docs/contracts/settlement-contract-freeze.md (SC-3, SC-5, SC-10)

The storage layer keeps the three guarantees the domain states, because a guarantee the database does
not enforce is a guarantee two concurrent requests can forget:

* `uq_settlement_orders_intent` — one order per intent. A replay cannot create a parallel order with a
  second hash (SC-3, SC-4).
* `pk settlement_nullifiers` — the nullifier is the primary key, so the "spend" is an insert and a
  second spend is an integrity error, not a lost update (SC-5, scenario 6). This is the last local lock.
* `uq_settlement_orders_tx_hash` — a hash belongs to exactly one order. The hash is the write-ahead
  record (SC-3), so two orders sharing one means two orders claiming one payment.
* `ck_settlement_orders_status` — the stored status is one `SettlementStatus` declares. Since the two
  phase write path there is a state between "order exists" and "the chain has it" (`signed`), and a row
  in a state the domain cannot name is an order the recovery procedure does not cover.

`settlement_receipts` is append-only and deliberately has **no** uniqueness on `tx_hash`: a reorg or a
deeper confirmation is a new fact about the same hash, not an update (SC-7). It carries gas and fee as
required columns because a receipt without cost cannot be accounted for (SC-10).

The chain addresses live on the order row, not in a settings table: an order rehydrated after a restart
must remember the network it was signed for, or a re-poll could read the wrong chain (SC-11).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

__all__ = [
    "Base",
    "SettlementNullifierRow",
    "SettlementOrderRow",
    "SettlementOutboxRow",
    "SettlementReceiptRow",
]

#: The closed lifecycle `SettlementStatus` declares, mirrored into a CHECK constraint (migration
#: `005_settlement_signed`). A status the domain cannot name must not be storable: a row in an unknown
#: state is an order no state machine owns, and the recovery procedure silently stops applying.
STATUS_VALUES: tuple[str, ...] = (
    "ordered",
    "signed",
    "submitted",
    "pending",
    "confirmed",
    "reverted",
    "abandoned",
)


class Base(DeclarativeBase):
    """Declarative base for the Settlement schema (`settlement_*` tables)."""


class SettlementOrderRow(Base):
    """The aggregate root, flattened. `tx_hash` is the write-ahead record (SC-3)."""

    __tablename__ = "settlement_orders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    intent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    invoice_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payee_address: Mapped[str] = mapped_column(String(42), nullable=False)
    amount_micro_usdc: Mapped[int] = mapped_column(Integer, nullable=False)
    nullifier: Mapped[str] = mapped_column(String(66), nullable=False)

    #: The network the order was signed for, stored with the order so a re-poll cannot switch chains.
    chain_id: Mapped[int] = mapped_column(Integer, nullable=False)
    router_address: Mapped[str] = mapped_column(String(42), nullable=False)
    usdc_address: Mapped[str] = mapped_column(String(42), nullable=False)
    confirmations_required: Mapped[int] = mapped_column(Integer, nullable=False)

    #: Mandate's verified digest, copied at order time (SC-2).
    bank_digest: Mapped[str] = mapped_column(Text, nullable=False)
    is_new_payee: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_owner_signature: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False)
    #: `NULL` before signing; never `NULL` afterwards. `uq_…_tx_hash` ignores NULLs.
    tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    #: The signed bytes that carry `tx_hash`. Written with the hash so the write-ahead record is
    #: re-broadcastable without re-signing (SC-3): a crash between signing and sending is recovered by
    #: replaying the same transaction, never by taking a second nonce.
    raw_transaction: Mapped[str | None] = mapped_column(Text, nullable=True)

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("intent_id", name="uq_settlement_orders_intent"),
        UniqueConstraint("nullifier", name="uq_settlement_orders_nullifier"),
        UniqueConstraint("tx_hash", name="uq_settlement_orders_tx_hash"),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{value}'" for value in STATUS_VALUES) + ")",
            name="ck_settlement_orders_status",
        ),
        Index("ix_settlement_orders_status", "status"),
        Index("ix_settlement_orders_invoice", "invoice_id"),
    )


class SettlementNullifierRow(Base):
    """The spent-marker table. The primary key *is* the unique constraint (SC-5)."""

    __tablename__ = "settlement_nullifiers"

    nullifier: Mapped[str] = mapped_column(String(66), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    spent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_settlement_nullifiers_order", "order_id"),)


class SettlementReceiptRow(Base):
    """One immutable chain fact. Append-only; cost columns are required (SC-7, SC-10)."""

    __tablename__ = "settlement_receipts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tx_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    block_number: Mapped[int] = mapped_column(Integer, nullable=False)
    confirmations: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    gas_used: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Wei as a decimal string; wei does not fit a 32-bit integer and JS cannot hold it as a number.
    gas_price: Mapped[str] = mapped_column(Text, nullable=False)
    fee_micro_usdc: Mapped[int] = mapped_column(Integer, nullable=False)
    is_anchor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revert_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_settlement_receipts_order", "order_id"),
        Index("ix_settlement_receipts_observed", "observed_at"),
    )


class SettlementOutboxRow(Base):
    """Transactional outbox (ADR-003): events are written in the state's own transaction."""

    __tablename__ = "settlement_outbox"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_name: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_settlement_outbox_unpublished", "published_at"),)
