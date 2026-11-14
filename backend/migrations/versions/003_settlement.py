"""003_settlement — orders, spent nullifiers, receipts and the outbox.

Canonical: .pi/architecture/decisions/ADR-002-data-storage-strategy.md
Reference: docs/contracts/settlement-contract-freeze.md (SC-3, SC-5, SC-10)

Storage-level guarantees the settlement contract states as invariants:

* `uq_settlement_orders_intent` — one order per intent, so a replay cannot create a parallel order
  with a second hash (SC-3, SC-4).
* `pk settlement_nullifiers` — the nullifier is the primary key, so "spend" is an insert and the second
  spend is an integrity error; this is the last local lock behind scenario 6 (SC-5).
* `uq_settlement_orders_tx_hash` — a hash belongs to one order (SC-3). NULLs are allowed and SQLite /
  PostgreSQL both ignore them in a unique constraint, so an `ORDERED` order is unaffected.
* `settlement_receipts` has **no** unique `tx_hash`: a deeper confirmation is a new fact, not an update
  (SC-7). Gas and fee are `NOT NULL` because a receipt without cost cannot be accounted for (SC-10).

Revision ID: 003_settlement
Revises: 002_billing
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003_settlement"
down_revision: str | None = "002_billing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "settlement_orders",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("intent_id", sa.String(64), nullable=False),
        sa.Column("invoice_id", sa.String(128), nullable=False),
        sa.Column("payee_address", sa.String(42), nullable=False),
        sa.Column("amount_micro_usdc", sa.Integer(), nullable=False),
        sa.Column("nullifier", sa.String(66), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("router_address", sa.String(42), nullable=False),
        sa.Column("usdc_address", sa.String(42), nullable=False),
        sa.Column("confirmations_required", sa.Integer(), nullable=False),
        sa.Column("bank_digest", sa.Text(), nullable=False),
        sa.Column("is_new_payee", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "requires_owner_signature", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("tx_hash", sa.String(66), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        # SC-3 / SC-4: one order per intent, one hash per order, one owner per nullifier.
        sa.UniqueConstraint("intent_id", name="uq_settlement_orders_intent"),
        sa.UniqueConstraint("nullifier", name="uq_settlement_orders_nullifier"),
        sa.UniqueConstraint("tx_hash", name="uq_settlement_orders_tx_hash"),
    )
    op.create_index("ix_settlement_orders_status", "settlement_orders", ["status"])
    op.create_index("ix_settlement_orders_invoice", "settlement_orders", ["invoice_id"])

    op.create_table(
        "settlement_nullifiers",
        # SC-5: the primary key is the unique constraint; a second spend is an integrity error.
        sa.Column("nullifier", sa.String(66), primary_key=True),
        sa.Column("order_id", sa.String(64), nullable=False),
        sa.Column("spent_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_settlement_nullifiers_order", "settlement_nullifiers", ["order_id"])

    op.create_table(
        "settlement_receipts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("order_id", sa.String(64), nullable=False),
        sa.Column("tx_hash", sa.String(66), nullable=False),
        sa.Column("block_number", sa.Integer(), nullable=False),
        sa.Column("confirmations", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        # SC-10: cost is required, never defaulted to zero.
        sa.Column("gas_used", sa.Integer(), nullable=False),
        sa.Column("gas_price", sa.Text(), nullable=False),
        sa.Column("fee_micro_usdc", sa.Integer(), nullable=False),
        sa.Column("is_anchor", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revert_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_settlement_receipts_order", "settlement_receipts", ["order_id"])
    op.create_index("ix_settlement_receipts_observed", "settlement_receipts", ["observed_at"])

    op.create_table(
        "settlement_outbox",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("event_name", sa.String(80), nullable=False),
        sa.Column("aggregate_id", sa.String(64), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_settlement_outbox_unpublished", "settlement_outbox", ["published_at"])


def downgrade() -> None:
    op.drop_table("settlement_outbox")

    op.drop_index("ix_settlement_receipts_observed", table_name="settlement_receipts")
    op.drop_index("ix_settlement_receipts_order", table_name="settlement_receipts")
    op.drop_table("settlement_receipts")

    op.drop_index("ix_settlement_nullifiers_order", table_name="settlement_nullifiers")
    op.drop_table("settlement_nullifiers")

    op.drop_index("ix_settlement_orders_invoice", table_name="settlement_orders")
    op.drop_index("ix_settlement_orders_status", table_name="settlement_orders")
    op.drop_table("settlement_orders")
