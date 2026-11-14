"""Authority repository ports — owned by `domain/` (frozen).

Canonical: docs/architecture/modules/authority.md#components
Reference: docs/contracts/authority-contract-freeze.md §2

    PaymentIntentRepository   add · find_by_id · save
    DeterminationRepository   append · find_by_intent
    CapLedgerRepository       try_reserve_atomic · resolve · ledger_for
    ApprovalRepository        add · find_by_id · save

Two signature-level decisions carry invariants:

* **`DeterminationRepository.append` has no `save`.** A determination is immutable (A-1's sibling); an
  update path would let a verdict be revised after the fact.
* **`CapLedgerRepository.try_reserve_atomic` returns a bool.** That is A-9's atomicity expressed in the
  port: the adapter performs one conditional `UPDATE` and reports whether it matched a row. Returning the
  ledger instead would invite read-then-write, which is the bug the invariant names.

No port exposes transaction control: the unit of work belongs to the application layer (ADR-002).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.authority.domain.approval import Approval
from src.authority.domain.cap_ledger import CapLedger, Reservation
from src.authority.domain.determination import Determination
from src.authority.domain.ids import ApprovalId, IntentId, ReservationId
from src.authority.domain.payment_intent import PaymentIntent
from src.authority.domain.values import Money
from src.shared.domain.repository import Repository

__all__ = [
    "ApprovalRepository",
    "CapLedgerRepository",
    "DeterminationRepository",
    "PaymentIntentRepository",
]


class PaymentIntentRepository(Repository[IntentId, PaymentIntent], ABC):
    """Persistence port for the PaymentIntent aggregate (immutable, so add + read only)."""

    @abstractmethod
    async def add(self, intent: PaymentIntent) -> None:
        """Insert the intent once. There is no update path: an issued intent is final (A-1)."""
        raise NotImplementedError("A-1 — see module doc")

    @abstractmethod
    async def find_by_id(self, id_: IntentId) -> PaymentIntent | None:
        raise NotImplementedError("A-1 — see module doc")

    @abstractmethod
    async def save(self, intent: PaymentIntent) -> None:
        """Persist the aggregate version (optimistic concurrency). Never mutates the intent's fields."""
        raise NotImplementedError("A-1 — see module doc")


class DeterminationRepository(ABC):
    """Append-only persistence for verdicts.

    Deliberately **not** a `Repository[...]`: the shared base declares `save`, and inheriting it would hand
    the port a revision path that A-7 forbids. The absence has to be structural, or an adapter will use it.
    """

    @abstractmethod
    async def append(self, determination: Determination) -> None:
        raise NotImplementedError("A-7 — see module doc")

    @abstractmethod
    async def find_by_intent(self, intent_id: IntentId) -> Determination | None:
        """The verdict for an intent, or None. The dispatch gate reads exactly this (A-8)."""
        raise NotImplementedError("A-8 — see module doc")


class CapLedgerRepository(ABC):
    """The ledger's atomicity boundary (A-9)."""

    @abstractmethod
    async def try_reserve_atomic(self, day: str, amount: Money, reservation: Reservation) -> bool:
        """Apply the reservation iff `committed + reserved + amount <= cap`, in one statement.

        Returns False when the conditional update matched no row (headroom insufficient) — the caller
        turns that into `CapExceeded`, and nothing was reserved.
        """
        raise NotImplementedError("A-9 — see module doc")

    @abstractmethod
    async def resolve(self, reservation_id: ReservationId, outcome: str) -> None:
        """Commit or release, once (A-10). `outcome` is `committed` or `released`."""
        raise NotImplementedError("A-10 — see module doc")

    @abstractmethod
    async def ledger_for(self, day: str) -> CapLedger:
        """The ledger row for a day; a rollover creates a new row (A-12)."""
        raise NotImplementedError("A-12 — see module doc")


class ApprovalRepository(Repository[ApprovalId, Approval], ABC):
    """Persistence port for approvals."""

    @abstractmethod
    async def add(self, approval: Approval) -> None:
        raise NotImplementedError("A-13 — see module doc")

    @abstractmethod
    async def find_by_id(self, id_: ApprovalId) -> Approval | None:
        raise NotImplementedError("A-13 — see module doc")

    @abstractmethod
    async def find_pending(self) -> list[Approval]:
        """Unconsumed, unexpired approvals — the owner's inbox (Console projects this)."""
        raise NotImplementedError("A-14 — see module doc")

    @abstractmethod
    async def save(self, approval: Approval) -> None:
        raise NotImplementedError("A-14 — see module doc")
