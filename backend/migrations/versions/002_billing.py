"""002_billing — invoices, attempts and the outbox.

Canonical: .pi/architecture/decisions/ADR-002-data-storage-strategy.md
Reference: .pi/architecture/modules/billing.md#components

Storage-level guarantees the module doc states as invariants:

* `uq_billing_invoices_hash` — the invoice hash is the insert key (B-3), so a replayed bill cannot
  become a second row even if two requests race the service's duplicate lookup.
* `uq_billing_attempts_one_active` — a **partial** unique index on `invoice_id` for every status that
  is not terminal (B-1). This is the concurrency backstop behind "at most one attempt"; the domain
  guard raises first so the caller gets `InvoiceNotPayable`, but the database is what makes it true.
* Routing details are deliberately absent (B-4): only the presented digest is stored, so a database
  leak cannot redirect a payment.

Revision ID: 002_billing
Revises: 001_mandate
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "002_billing"
down_revision: str | None = "001_mandate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "billing_invoices",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("payee_id", sa.String(64), nullable=False),
        sa.Column("invoice_hash", sa.Text(), nullable=False),
        sa.Column("amount_micro_usdc", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("presented_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        # B-3: the hash identifies the bill.
        sa.UniqueConstraint("invoice_hash", name="uq_billing_invoices_hash"),
    )
    op.create_index("ix_billing_invoices_status", "billing_invoices", ["status"])
    op.create_index("ix_billing_invoices_payee", "billing_invoices", ["payee_id"])

    op.create_table(
        "billing_attempts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "invoice_id",
            sa.String(64),
            sa.ForeignKey("billing_invoices.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # B-1: at most one non-terminal attempt per invoice (partial unique index).
    op.create_index(
        "uq_billing_attempts_one_active",
        "billing_attempts",
        ["invoice_id"],
        unique=True,
        sqlite_where=sa.text("status NOT IN ('refused', 'settled')"),
    )
    op.create_index("ix_billing_attempts_invoice", "billing_attempts", ["invoice_id"])

    op.create_table(
        "billing_outbox",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("event_name", sa.String(80), nullable=False),
        sa.Column("aggregate_id", sa.String(64), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_billing_outbox_unpublished", "billing_outbox", ["published_at"])


def downgrade() -> None:
    op.drop_index("ix_billing_outbox_unpublished", table_name="billing_outbox")
    op.drop_table("billing_outbox")
    op.drop_index("ix_billing_attempts_invoice", table_name="billing_attempts")
    op.drop_index("uq_billing_attempts_one_active", table_name="billing_attempts")
    op.drop_table("billing_attempts")
    op.drop_index("ix_billing_invoices_payee", table_name="billing_invoices")
    op.drop_index("ix_billing_invoices_status", table_name="billing_invoices")
    op.drop_table("billing_invoices")
