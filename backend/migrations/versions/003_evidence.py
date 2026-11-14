"""003_evidence — append-only envelopes, anchors and the idempotency ledger.

Canonical: docs/architecture/decisions/ADR-002-data-storage-strategy.md
Reference: docs/contracts/evidence-contract-freeze.md §2.5

Storage-level guarantees the module doc states as invariants:

* `uq_evidence_anchors_hash` — one anchor per envelope hash (E-8). A second hash cannot borrow the
  first hash's proof; the adapter translates the conflict into `AnchorMismatch`.
* `evidence_processed_events` is keyed by `(event_id, handler)` — the idempotency claim (E-4).
* **Append-only triggers** abort a direct `UPDATE`/`DELETE` on every Evidence table (E-5). The
  repository has no update path in code; the trigger is the second line of defence for a hand-written
  statement, which is exactly what the acceptance criterion asks to be rejected.

No column holds the HMAC key (E-9): the signer owns it and only the resulting MAC is stored.

Revision ID: 003_evidence
Revises: 002_billing
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003_evidence"
down_revision: str | None = "002_billing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APPEND_ONLY_TABLES = ("evidence_envelopes", "evidence_anchors", "evidence_processed_events")


def upgrade() -> None:
    op.create_table(
        "evidence_envelopes",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("subject_intent_id", sa.String(64), nullable=True),
        sa.Column("subject_invoice_id", sa.String(64), nullable=True),
        sa.Column("subject_payee_id", sa.String(64), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("constitution_version", sa.String(20), nullable=True),
        sa.Column("actor", sa.String(40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hmac", sa.Text(), nullable=False),
        sa.Column("previous_hash", sa.String(64), nullable=True),
        sa.Column("anchor_mode", sa.String(20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "anchor_mode IN ('per_envelope','batched','demo_only')",
            name="ck_evidence_envelopes_anchor_mode",
        ),
    )
    op.create_index("ix_evidence_envelopes_intent", "evidence_envelopes", ["subject_intent_id"])
    op.create_index("ix_evidence_envelopes_invoice", "evidence_envelopes", ["subject_invoice_id"])
    op.create_index("ix_evidence_envelopes_payee", "evidence_envelopes", ["subject_payee_id"])
    op.create_index("ix_evidence_envelopes_occurred", "evidence_envelopes", ["occurred_at"])
    op.create_index("ix_evidence_envelopes_event_type", "evidence_envelopes", ["event_type"])

    op.create_table(
        "evidence_anchors",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("envelope_hash", sa.String(64), nullable=False),
        sa.Column("anchor_tx", sa.Text(), nullable=False),
        sa.Column("block_number", sa.Integer(), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("anchored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # E-8: the hash is the anchor's identity.
        sa.UniqueConstraint("envelope_hash", name="uq_evidence_anchors_hash"),
    )

    op.create_table(
        "evidence_processed_events",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("handler", sa.String(40), primary_key=True),
        sa.Column(
            "processed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    # E-5: no rewrite of a sealed fact, even by a statement that bypasses the adapter.
    for table in _APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'evidence is append-only'); END"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'evidence is append-only'); END"
        )


def downgrade() -> None:
    for table in _APPEND_ONLY_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update")
    op.drop_table("evidence_processed_events")
    op.drop_table("evidence_anchors")
    op.drop_index("ix_evidence_envelopes_event_type", table_name="evidence_envelopes")
    op.drop_index("ix_evidence_envelopes_occurred", table_name="evidence_envelopes")
    op.drop_index("ix_evidence_envelopes_payee", table_name="evidence_envelopes")
    op.drop_index("ix_evidence_envelopes_invoice", table_name="evidence_envelopes")
    op.drop_index("ix_evidence_envelopes_intent", table_name="evidence_envelopes")
    op.drop_table("evidence_envelopes")
