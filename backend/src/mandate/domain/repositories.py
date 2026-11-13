"""Repository ports — defined in `domain/`, implemented in `infrastructure/` (ADR-008).

Canonical: .pi/architecture/modules/mandate.md#components
Reference: .pi/architecture/decisions/ADR-002-data-storage-strategy.md

The issue boilerplate suggested `infrastructure/repository/`; this project puts the **interfaces**
in `domain/` because ADR-008's `interface-ownership` gate requires the domain to own the port it
depends on, and because the module doc already declares "Repository interfaces (owned by
`domain/`)". Implementations go in `src/mandate/infrastructure/repositories.py` in the persistence
item. Concrete routers/controllers stay concrete (no interface), per the issue.

Frozen contract v1. Three rules encoded in the signatures:

1. **No commit.** A repository participates in a unit of work owned by an application service
   (`src/shared/application/unit_of_work.py`); it never opens or closes a transaction.
2. **Read-through, never cached.** `find_in_force` exists as its own method so Authority's
   dispatch-time read (FR-012) has one obvious, cache-free call site.
3. **Aggregates in, aggregates out.** No row types, no ORM models, no `dict` — the database schema
   is explicitly out of the frozen contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.mandate.domain.constitution import Constitution, ConstitutionVersion
from src.mandate.domain.household import Household
from src.mandate.domain.ids import ConstitutionId, HouseholdId, PayeeId
from src.mandate.domain.payee import Payee
from src.shared.domain.repository import Repository

__all__ = ["ConstitutionRepository", "HouseholdRepository", "PayeeRepository"]


class HouseholdRepository(Repository[HouseholdId, Household], ABC):
    """Persistence port for the Household aggregate root."""

    @abstractmethod
    async def find_by_id(self, id_: HouseholdId) -> Household | None:
        """Return the household or None. Never raises for absence."""
        raise NotImplementedError

    @abstractmethod
    async def save(self, household: Household) -> None:
        """Persist within the caller's unit of work. No commit here."""
        raise NotImplementedError


class ConstitutionRepository(Repository[ConstitutionId, Constitution], ABC):
    """Persistence port for the Constitution aggregate root."""

    @abstractmethod
    async def find_by_id(self, id_: ConstitutionId) -> Constitution | None:
        raise NotImplementedError

    @abstractmethod
    async def find_in_force(self, household_id: HouseholdId) -> ConstitutionVersion:
        """The single in-force version.

        Must read through on every call — no cache, no plan-time snapshot (FR-012, "moment of
        consequence"). Raises `ConstitutionCorrupted` if the invariant H-4 is violated in storage.
        """
        raise NotImplementedError

    @abstractmethod
    async def find_version(
        self, constitution_id: ConstitutionId, number: int
    ) -> ConstitutionVersion:
        """A historical version, so a past refusal stays explainable after supersession (H-7)."""
        raise NotImplementedError

    @abstractmethod
    async def save(self, constitution: Constitution) -> None:
        raise NotImplementedError


class PayeeRepository(Repository[PayeeId, Payee], ABC):
    """Persistence port for the Payee aggregate root."""

    @abstractmethod
    async def find_by_id(self, id_: PayeeId) -> Payee | None:
        raise NotImplementedError

    @abstractmethod
    async def find_by_household(self, household_id: HouseholdId) -> list[Payee]:
        raise NotImplementedError

    @abstractmethod
    async def save(self, payee: Payee) -> None:
        raise NotImplementedError
