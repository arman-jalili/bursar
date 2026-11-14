"""005_settlement_signed — the `signed` state and the signed bytes that carry the hash.

Canonical: docs/architecture/modules/settlement.md#aggregate-settlementorder
Reference: docs/contracts/settlement-contract-freeze.md §2.8 and §7 (the two-phase `ChainGateway`)

SC-3 requires the tx hash to be persisted **before** broadcast. Signing is local, so there is a real
state in between: the payment is signed (hash known, bytes in hand) and nothing has been sent. This
migration makes that state storable and checkable:

* `raw_transaction` — the signed bytes, stored beside the hash. A crash between signing and broadcasting
  is recovered by re-sending these bytes (one transaction, one nonce), never by signing a second one. A
  hash without its bytes would be a record an operator cannot act on.
* `ck_settlement_orders_status` — the stored status is one the domain declares. `signed` is added to the
  closed set, and a status nobody can name must not be insertable: a row in an unknown state is an order
  the recovery procedure does not cover.

SQLite cannot `ADD CONSTRAINT`, so the constraint arrives with a batch table rebuild. The unique
constraints and indexes are carried over by Alembic's reflection; they are re-declared in `downgrade`
only to the extent the rebuild needs them.

Revision ID: 005_settlement_signed
Revises: 004_authority
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005_settlement_signed"
down_revision: str | None = "004_authority"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The closed lifecycle from `domain.values.SettlementStatus`, in the order the enum declares it.
STATUS_VALUES: tuple[str, ...] = (
    "ordered",
    "signed",
    "submitted",
    "pending",
    "confirmed",
    "reverted",
    "abandoned",
)


def _status_check() -> str:
    return "status IN (" + ", ".join(f"'{value}'" for value in STATUS_VALUES) + ")"


def upgrade() -> None:
    with op.batch_alter_table("settlement_orders", recreate="always") as batch:
        # SC-3: the signed bytes live next to the hash they hash to.
        batch.add_column(sa.Column("raw_transaction", sa.Text(), nullable=True))
        # The new state, and every other one, enforced by the database rather than by convention.
        batch.create_check_constraint("ck_settlement_orders_status", _status_check())


def downgrade() -> None:
    # Any `signed` row must be resolved (broadcast or abandoned) before this column drops: on the way
    # down, the state that produced the hash is no longer representable.
    op.execute("UPDATE settlement_orders SET status = 'ordered' WHERE status = 'signed'")
    with op.batch_alter_table("settlement_orders", recreate="always") as batch:
        batch.drop_constraint("ck_settlement_orders_status", type_="check")
        batch.drop_column("raw_transaction")
