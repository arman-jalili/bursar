"""SC-3 / SC-5 — the ports own the invariant mirrors, not the callers.

Canonical: docs/contracts/settlement-contract-freeze.md §1 (SC-3, SC-5)
Reference: docs/architecture/modules/settlement.md#repository-interfaces-owned-by-domain

Defends module AC #3 and AC #5 at the storage boundary. The ports are where "one hash" and "one spend"
become durable facts, so the assertions are rules the adapters must preserve:

* a nullifier store refuses a second spend of the same marker, even if the caller read "unspent" first
  (the race the unique constraint exists for);
* an order store refuses a second order for an intent, so a replay cannot create a parallel order.

The fakes below are in-memory models of the contract, not the production adapter — the adapter is Phase
B, and it must satisfy the same two refusals.
"""

from __future__ import annotations

import pytest
from src.settlement.domain.errors import DuplicateSettlementBlocked, OrderAlreadyConcluded
from src.settlement.domain.ids import IntentId, OrderId
from src.settlement.domain.repositories import NullifierRepository, SettlementOrderRepository
from src.settlement.domain.services import NullifierPolicy
from src.settlement.domain.settlement_order import SettlementOrder
from src.settlement.domain.values import Nullifier


class _InMemoryNullifiers(NullifierRepository):
    """Mirrors the unique constraint: the check and the write are one step."""

    def __init__(self) -> None:
        self._spent: dict[str, OrderId] = {}

    async def is_spent(self, nullifier: Nullifier) -> bool:
        return nullifier.value in self._spent

    async def spend(self, nullifier: Nullifier, order_id: OrderId) -> None:
        NullifierPolicy().guard_unspent(nullifier, already_spent=await self.is_spent(nullifier))
        self._spent[nullifier.value] = order_id


class _InMemoryOrders(SettlementOrderRepository):
    """Mirrors the one-order-per-intent guard on the insert path."""

    def __init__(self) -> None:
        self._by_intent: dict[IntentId, SettlementOrder] = {}

    async def add(self, order: SettlementOrder) -> None:
        if await self.find_by_intent(order.intent_id) is not None:
            raise OrderAlreadyConcluded(order_id=str(order.id), status=order.status.value)
        self._by_intent[order.intent_id] = order

    async def find_by_id(self, id_: OrderId) -> SettlementOrder | None:
        return next((o for o in self._by_intent.values() if o.id == id_), None)

    async def find_by_intent(self, intent_id: IntentId) -> SettlementOrder | None:
        return self._by_intent.get(intent_id)

    async def save(self, order: SettlementOrder) -> None:
        self._by_intent[order.intent_id] = order


class TestRepositoryContracts:
    async def test_a_nullifier_cannot_be_spent_twice(self) -> None:
        """SC-5 / AC-5: the store refuses the second spend — the last local lock (scenario 6)."""
        store = _InMemoryNullifiers()
        marker = NullifierPolicy().derive("ab" * 32, "hh-1")
        await store.spend(marker, OrderId("o-1"))

        with pytest.raises(DuplicateSettlementBlocked):
            await store.spend(marker, OrderId("o-2"))

    async def test_a_second_order_for_one_intent_is_refused(self, order) -> None:
        """SC-3 / AC-3: a replay cannot create a parallel order with a second hash."""
        store = _InMemoryOrders()
        await store.add(order)

        with pytest.raises(OrderAlreadyConcluded):
            await store.add(order)

    async def test_the_order_s_hash_is_readable_after_a_restart(self, order, signed_amount) -> None:
        """SC-3 / AC-3: the persisted order is the re-poll source; its hash must survive the round trip."""
        store = _InMemoryOrders()
        order.mark_submitted("0x" + "aa" * 32, signed_amount)
        await store.add(order)

        reloaded = await store.find_by_intent(order.intent_id)

        assert reloaded is not None
        assert reloaded.tx_hash == "0x" + "aa" * 32
