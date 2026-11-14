"""merge settlement and evidence heads

Canonical: .pi/architecture/decisions/ADR-002-data-storage-strategy.md
Revision: a52cc03d1e5a
Revises: 003_evidence, 003_settlement
Created: 2026-11-14 01:20:15.059849
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "a52cc03d1e5a"
down_revision: str | None = ("003_evidence", "003_settlement")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
