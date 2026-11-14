"""Settlement repository ports — owned by `domain/` (frozen).

Canonical: docs/architecture/modules/settlement.md#repository-interfaces-owned-by-domain
Reference: docs/contracts/settlement-contract-freeze.md §2.7

    SettlementOrderRepository   add (SC-3 write-ahead) · find_by_id · find_by_intent · save
    NullifierRepository         is_spent · spend (unique constraint = the last local lock, SC-5)
    ChainReceiptRepository      append · find_by_order · list_for_day (the only source of SC-10)

Three rules are expressed by the signatures rather than left to convention:

1. **No transaction control.** No `commit`, `flush` or `begin`: the unit of work belongs to the
   application layer (ADR-002). That is what makes "the hash is persisted in the same transaction that
   precedes broadcast" a checkable ordering (SC-3).
2. **`add` is not `save`.** `add` is the insert path and refuses a duplicate order for an intent
   (`SC-4`) or a spent nullifier (`SC-5`); `save` is the update path. Collapsing them would move the
   invariants into an upsert where nobody reads them.
3. **`spend` is a write, `is_spent` is the read.** The unique constraint in `spend` is the database's
   copy of SC-5: two racing use cases cannot both spend one nullifier even if both read "unspent".

`list_for_day` exists so `CostSummary` derives from receipts only (ADR-006) — a summary computed from
anything else would be a competing balance.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from src.authority.domain.ids import IntentId
from src.settlement.domain.chain_receipt import ChainReceipt
from src.settlement.domain.ids import OrderId
from src.settlement.domain.settlement_order import SettlementOrder
from src.settlement.domain.values import Nullifier
from src.shared.domain.repository import Repository

__all__ = ["ChainReceiptRepository", "NullifierRepository", "SettlementOrderRepository"]


class SettlementOrderRepository(Repository[OrderId, SettlementOrder], ABC):
    """Persistence port for the SettlementOrder aggregate root."""

    @abstractmethod
    async def add(self, order: SettlementOrder) -> None:
        """Insert the order — the write that must land before broadcast (SC-3).

        Raises:
            OrderAlreadyConcluded: an order already exists for this intent (scenario 6 replay).
        """
        raise NotImplementedError("SC-3 — see module doc")

    @abstractmethod
    async def find_by_id(self, id_: OrderId) -> SettlementOrder | None:
        """Return the order or None. Never raises for absence."""
        raise NotImplementedError("SC-4 — see module doc")

    @abstractmethod
    async def find_by_intent(self, intent_id: IntentId) -> SettlementOrder | None:
        """The single order for an intent, or None. The replay lookup (SC-4, scenario 6)."""
        raise NotImplementedError("SC-4 — see module doc")

    @abstractmethod
    async def save(self, order: SettlementOrder) -> None:
        """Update the order inside the caller's unit of work. No commit here."""
        raise NotImplementedError("SC-3 — see module doc")


class NullifierRepository(ABC):
    """The local anti-double-pay marker store (SC-5)."""

    @abstractmethod
    async def is_spent(self, nullifier: Nullifier) -> bool:
        """True when the marker has been consumed for this scope; read-through, no cache."""
        raise NotImplementedError("SC-5 — see module doc")

    @abstractmethod
    async def spend(self, nullifier: Nullifier, order_id: OrderId) -> None:
        """Consume the marker. The unique constraint is the last local lock.

        Raises:
            DuplicateSettlementBlocked: the marker is already spent — including the race where two
                use cases both observed `unspent` and then tried to spend.
        """
        raise NotImplementedError("SC-5 — see module doc")


class ChainReceiptRepository(ABC):
    """Append-only receipt store — the only input to cost accounting (SC-10)."""

    @abstractmethod
    async def append(self, receipt: ChainReceipt) -> None:
        """Append one chain fact. Receipts are never updated: a reorg is a new fact."""
        raise NotImplementedError("SC-10 — see module doc")

    @abstractmethod
    async def find_by_order(self, order_id: OrderId) -> ChainReceipt | None:
        """The latest receipt for an order, or None. The re-poll lookup (SC-3)."""
        raise NotImplementedError("SC-7 — see module doc")

    @abstractmethod
    async def list_for_day(self, day: date) -> tuple[ChainReceipt, ...]:
        """Every receipt observed on `day`, for `CostSummary` (ADR-006, SC-10)."""
        raise NotImplementedError("SC-10 — see module doc")
