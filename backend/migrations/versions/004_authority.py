"""004_authority — intents, determinations, the cap ledger, reservations, approvals, outbox.

Canonical: docs/architecture/decisions/ADR-002-data-storage-strategy.md
Reference: docs/architecture/modules/authority.md#components

Storage-level guarantees, each tied to an invariant:

* `authority_cap_ledger.day` is the primary key — a rollover is a new row (A-12), never a reset.
* `ck_authority_cap_ledger_within_cap` is a CHECK constraint: the database itself refuses a row where
  `committed + reserved > cap` (A-9). The conditional UPDATE in the adapter is the primary guard; this is
  the second one that survives a bug in a future code path.
* `authority_determinations.intent_id` is UNIQUE — a verdict is appended once and never revised (A-7).
* `uq_authority_reservation_intent` — one reservation per intent, so a single authorization cannot hold
  the same capacity twice.
* Amounts are `INTEGER` micro-USDC (ADR-002). No floats anywhere in the ledger.

Revision ID: 004_authority
Revises: a52cc03d1e5a
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004_authority"
down_revision: str | None = "a52cc03d1e5a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "authority_payment_intents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("invoice_id", sa.String(64), nullable=False),
        sa.Column("payee_id", sa.String(64), nullable=False),
        sa.Column("payee_address", sa.String(42), nullable=False),
        sa.Column("amount_micro_usdc", sa.Integer(), nullable=False),
        sa.Column("bank_digest", sa.String(64), nullable=False),
        sa.Column("is_new_payee", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "requires_owner_signature", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("constitution_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_authority_payment_intents_payee", "authority_payment_intents", ["payee_id"]
    )
    op.create_index(
        "ix_authority_payment_intents_invoice", "authority_payment_intents", ["invoice_id"]
    )

    op.create_table(
        "authority_determinations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("intent_id", sa.String(64), nullable=False),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("reason_codes", sa.String(200), nullable=False, server_default=""),
        sa.Column("constitution_version", sa.Integer(), nullable=False),
        sa.Column("payee_status_read", sa.String(20), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ledger_snapshot_micro_usdc", sa.Integer(), nullable=False),
        sa.UniqueConstraint("intent_id", name="uq_authority_determination_intent"),
    )

    op.create_table(
        "authority_cap_ledger",
        sa.Column("day", sa.String(10), primary_key=True),
        sa.Column("cap_micro_usdc", sa.Integer(), nullable=False),
        sa.Column("committed_micro_usdc", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reserved_micro_usdc", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "committed_micro_usdc + reserved_micro_usdc <= cap_micro_usdc",
            name="ck_authority_cap_ledger_within_cap",
        ),
    )

    op.create_table(
        "authority_reservations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("intent_id", sa.String(64), nullable=False),
        sa.Column("amount_micro_usdc", sa.Integer(), nullable=False),
        sa.Column("day", sa.String(10), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="held"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("intent_id", name="uq_authority_reservation_intent"),
    )
    op.create_index("ix_authority_reservations_day", "authority_reservations", ["day"])
    op.create_index("ix_authority_reservations_status", "authority_reservations", ["status"])

    op.create_table(
        "authority_approvals",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("intent_id", sa.String(64), nullable=False),
        sa.Column("typed_data_hash", sa.String(66), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signature_hex", sa.String(200), nullable=True),
        sa.Column("signer", sa.String(42), nullable=True),
        sa.Column("signed_digest", sa.String(66), nullable=True),
    )
    op.create_index(
        "ix_authority_approvals_pending", "authority_approvals", ["consumed_at", "expires_at"]
    )

    op.create_table(
        "authority_outbox",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("event_name", sa.String(80), nullable=False),
        sa.Column("aggregate_id", sa.String(64), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_authority_outbox_unpublished", "authority_outbox", ["published_at"])


def downgrade() -> None:
    op.drop_index("ix_authority_outbox_unpublished", table_name="authority_outbox")
    op.drop_table("authority_outbox")
    op.drop_index("ix_authority_approvals_pending", table_name="authority_approvals")
    op.drop_table("authority_approvals")
    op.drop_index("ix_authority_reservations_status", table_name="authority_reservations")
    op.drop_index("ix_authority_reservations_day", table_name="authority_reservations")
    op.drop_table("authority_reservations")
    op.drop_table("authority_cap_ledger")
    op.drop_table("authority_determinations")
    op.drop_index("ix_authority_payment_intents_invoice", table_name="authority_payment_intents")
    op.drop_index("ix_authority_payment_intents_payee", table_name="authority_payment_intents")
    op.drop_table("authority_payment_intents")
