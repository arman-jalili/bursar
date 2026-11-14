"""Mandate — household, parties, payees and the constitution.

Canonical: docs/architecture/modules/mandate.md
Reference: docs/architecture/decisions/ADR-001-architecture-pattern.md

The single source of truth for **what is allowed**. Mandate answers "who may be paid, up to how
much, under which rules" — Authority asks, at the moment of consequence. It never decides a
specific payment, and nothing in this package may import from another context.

Contract freeze status: **v1 frozen** (see `docs/architecture/modules/mandate.md#frozen-contracts-v1`).
Implementation items fill in the stub bodies; they must not change these signatures without a
new contract version.
"""

__contract_version__ = "1.0.0"
