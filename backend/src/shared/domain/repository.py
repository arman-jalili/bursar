"""Repository — the persistence port, owned by the domain layer.

Canonical: .pi/architecture/decisions/ADR-002-data-storage-strategy.md
Reference: .pi/architecture/modules/authority.md#components

ADR-008 `interface-ownership`: the ABC lives in `domain/`, the SQLAlchemy implementation lives in
`infrastructure/`. The gate `.pi/scripts/languages/python/check_model_judgment.sh` fails the build
if an adapter exists without a domain-owned interface.

Transaction placement (ADR-002 / txn-placement gate): a repository does **not** commit. Exactly
one application service owns one unit of work, so an aggregate is loaded and stored inside a
transaction the *use case* controls. A repository that commits on its own would break the atomic
cap reservation, which is the whole reason the ledger is safe.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

__all__ = ["Repository"]


class Repository[IdT, AggregateT](ABC):
    """Minimal persistence port. No commit, no flush, no transaction management.

    PEP 695 type parameters (Python 3.12+) rather than `Generic[...]`: subclasses declare
    `Repository[PayeeId, Payee]` without importing TypeVars, and the constraint stays local.
    """

    @abstractmethod
    async def find_by_id(self, id_: IdT) -> AggregateT | None:
        """Return the aggregate or None. Never raises for absence."""

    @abstractmethod
    async def save(self, aggregate: AggregateT) -> None:
        """Persist within the caller's unit of work. No commit here."""
