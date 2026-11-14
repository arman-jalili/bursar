"""001_mandate — household, constitution lineage, payees, outbox.

Canonical: docs/architecture/decisions/ADR-002-data-storage-strategy.md
Reference: docs/architecture/modules/mandate.md#components

Storage-level guarantees the module doc states as invariants:

* `uq_mandate_constitution_version` — one row per (constitution, version), so H-8 (contiguous,
  addressable history) cannot be violated by a duplicate insert.
* `uq_mandate_constitution_one_in_force` — a **partial** unique index on `status = 'in_force'`, which
  is invariant H-4 enforced where it cannot be forgotten: the database refuses a second live version.
* `uq_mandate_payee_name` — P-1's uniqueness per household.
* Routing details are deliberately absent: only the digest is stored, so a database leak cannot
  redirect a payment.

Revision ID: 001_mandate
Revises: 000_bootstrap
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "001_mandate"
down_revision: str | None = "000_bootstrap"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mandate_households",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("owner_address", sa.String(42), nullable=False),
        sa.Column("owner_name", sa.String(120), nullable=False),
        sa.Column("payer_id", sa.String(64), nullable=False),
        sa.Column("payer_name", sa.String(120), nullable=False),
        sa.Column("payer_contact", sa.String(200), nullable=False, server_default=""),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("agent_key_id", sa.String(200), nullable=False),
        sa.Column("agent_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("constitution_id", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_mandate_households_owner", "mandate_households", ["owner_address"])

    op.create_table(
        "mandate_constitutions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("household_id", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_mandate_constitutions_household", "mandate_constitutions", ["household_id"])

    op.create_table(
        "mandate_constitution_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "constitution_id",
            sa.String(64),
            sa.ForeignKey("mandate_constitutions.id"),
            nullable=False,
        ),
        sa.Column("household_id", sa.String(64), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("cap_micro_usdc", sa.Integer(), nullable=False),
        sa.Column("threshold_micro_usdc", sa.Integer(), nullable=False),
        sa.Column(
            "require_signature_for_new_payee",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="in_force"),
        sa.UniqueConstraint("constitution_id", "number", name="uq_mandate_constitution_version"),
    )
    # H-4: at most one in-force version per household.
    op.create_index(
        "uq_mandate_constitution_one_in_force",
        "mandate_constitution_versions",
        ["household_id"],
        unique=True,
        sqlite_where=sa.text("status = 'in_force'"),
    )

    op.create_table(
        "mandate_payees",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("household_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("address", sa.String(42), nullable=False),
        sa.Column("verified_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("household_id", "name", name="uq_mandate_payee_name"),
    )
    op.create_index("ix_mandate_payees_status", "mandate_payees", ["status"])

    op.create_table(
        "mandate_outbox",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("event_name", sa.String(80), nullable=False),
        sa.Column("aggregate_id", sa.String(64), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mandate_outbox_unpublished", "mandate_outbox", ["published_at"])


def downgrade() -> None:
    op.drop_index("ix_mandate_outbox_unpublished", table_name="mandate_outbox")
    op.drop_table("mandate_outbox")
    op.drop_index("ix_mandate_payees_status", table_name="mandate_payees")
    op.drop_table("mandate_payees")
    op.drop_index(
        "uq_mandate_constitution_one_in_force", table_name="mandate_constitution_versions"
    )
    op.drop_table("mandate_constitution_versions")
    op.drop_index("ix_mandate_constitutions_household", table_name="mandate_constitutions")
    op.drop_table("mandate_constitutions")
    op.drop_index("ix_mandate_households_owner", table_name="mandate_households")
    op.drop_table("mandate_households")
