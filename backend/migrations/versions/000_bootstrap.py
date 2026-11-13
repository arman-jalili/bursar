"""000_bootstrap — migration tooling only; creates no tables.

Canonical: .pi/architecture/decisions/ADR-002-data-storage-strategy.md
Reference: .pi/architecture/implementation-roadmap.md#phase-0-project-bootstrap-hours-01

This revision exists so that `alembic upgrade head` / `downgrade base` are exercised on a clean
database before any context defines schema (Phase-0 acceptance criterion). It intentionally does
nothing: Phase 0 must not create table-shaped placeholders for contexts it has not modelled.

Revision ID: 000_bootstrap
Revises: None
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "000_bootstrap"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: verifies the migration chain, not the schema."""


def downgrade() -> None:
    """No-op: symmetric with upgrade, so a clean round-trip is provable."""
