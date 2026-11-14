"""`DispatchPayment` — the write path that turns an allowed intent into a governed dispatch.

Canonical: .pi/architecture/modules/settlement.md#application-services
Reference: docs/contracts/settlement-contract-freeze.md §2.10 (SC-1, SC-2, SC-5)

This is the concrete `DispatchPayment` the frozen catalog names. It lives in the application layer
because that is where the freeze puts it: one unit of work, one outbox append, no rule of its own. Every
rule below is a call into the aggregate or the domain services:

    SC-1  DeterminationGate is read live (no cache), then `SettlementOrder.order` refuses a verdict
          that does not permit dispatch — before anything is persisted.
    SC-2  The command path never appears here. The executor is handed the **order**; the adapter can
          only read `order.command_ref` / `order.command_params()`.
    SC-5  The nullifier is checked locally (and on-chain when a `ChainGateway` is installed) before the
          governed command runs; the store's unique constraint remains the last lock.

Scope, stated honestly — the chain write is **not** in this service yet
---------------------------------------------------------------------
`DispatchPaymentResult.tx_hash` stays `None` because no transaction is broadcast here. That is not an
omission to be papered over: `ChainGateway.submit(order) -> str` learns the hash only *after* broadcast,
so SC-3's "persist the hash before broadcast" cannot be expressed with the frozen port (blocker B-1, see
ADR-009 and the runbook). Inventing a hash, or marking an order `SUBMITTED` without one, would fake the
one ordering the commit-point lock depends on. The order therefore stays `ORDERED` with an execution
record behind it, and the chain adapter slice (G-1/B-1) owns `submit` → `mark_submitted`.

What the chain port *does* do here is the read: `is_nullifier_spent` is how the on-chain copy of SC-5
refuses a replay one layer before the contract, and it needs no write-ahead ordering. It is optional so
this composition can run before the chain adapter lands; when it is absent the local store is still the
last local lock (a database guarantee, not a comment).
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.authority.domain.ids import IntentId
from src.settlement.application.dto import DispatchPaymentCommand, DispatchPaymentResult
from src.settlement.application.services import DispatchPayment
from src.settlement.domain.errors import DuplicateSettlementBlocked
from src.settlement.domain.events import SettlementOrdered
from src.settlement.domain.ports import ChainGateway, DeterminationGate, PaymentExecutor
from src.settlement.domain.services import NullifierPolicy
from src.settlement.domain.settlement_order import SettlementOrder
from src.settlement.domain.values import ChainNetwork
from src.settlement.domain.views import PaymentIntentView
from src.settlement.infrastructure.repositories import (
    OutboxWriter,
    SqlNullifierRepository,
    SqlSettlementOrderRepository,
)
from src.shared.application.unit_of_work import session_scope
from src.shared.infrastructure.logging import get_logger

__all__ = ["DispatchPaymentService", "IntentSource"]

logger = get_logger(__name__)


class IntentSource(Protocol):
    """The frozen intent facts a dispatch needs, assembled from a live Authority read.

    Declared next to the use case that needs it rather than in `domain/ports.py`: the settlement freeze
    names exactly three ports (`PaymentExecutor`, `ChainGateway`, `DeterminationGate`), and this is an
    application-level read of another context's projection, not a fourth domain port. Infrastructure
    depends on this declaration (the allowed direction); the application layer imports no adapter.
    """

    async def intent_for(self, intent_id: IntentId) -> PaymentIntentView: ...


class DispatchPaymentService(DispatchPayment):
    """One dispatch: live authority → order → governed command (SC-1, SC-2, SC-5)."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        intents: IntentSource,
        determination: DeterminationGate,
        executor: PaymentExecutor,
        network: ChainNetwork,
        chain: ChainGateway | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._intents = intents
        self._determination = determination
        self._executor = executor
        self._network = network
        self._chain = chain

    async def execute(self, command: DispatchPaymentCommand) -> DispatchPaymentResult:
        """Create the order and run the fixed dispatch command for it.

        Raises:
            SettlementRefusal: the Authority reads failed closed (SC-1), the determination does not
                permit dispatch (SC-1), the invoice's nullifier is spent (SC-5), an order already
                exists for this intent (SC-4), or Rigorix refused / did not answer (SC-2). In every
                case no transaction was broadcast.
        """
        intent_id = IntentId(command.intent_id)

        # SC-1: two live reads, in this order. The intent facts are what the order freezes; the
        # determination is the permission, and it is read now rather than trusted from plan time.
        intent = await self._intents.intent_for(intent_id)
        determination = await self._determination.determination_for(intent_id)

        # SC-1: the factory is the only entry point, and it refuses before anything is persisted.
        order = SettlementOrder.order(intent, self._network, determination)

        async with session_scope(self._session_factory) as session:
            orders = SqlSettlementOrderRepository(session)
            existing = await orders.find_by_intent(intent_id)
            if existing is not None:
                # SC-4/SC-5: one order per intent. A replay is a duplicate settlement, never a second
                # dispatch — the refusal is what stops the second payment.
                raise DuplicateSettlementBlocked(
                    nullifier=existing.nullifier.value, order_id=str(existing.id)
                )

            policy = NullifierPolicy()
            policy.guard_unspent(
                order.nullifier,
                already_spent=await SqlNullifierRepository(session).is_spent(order.nullifier),
            )
            if self._chain is not None:
                policy.guard_unspent(
                    order.nullifier,
                    already_spent=await self._chain.is_nullifier_spent(order.nullifier),
                )

            await orders.add(order)
            # ADR-003: the aggregate records facts, the use case appends them in its own transaction.
            order.record(
                SettlementOrdered(
                    aggregate_id=str(order.id),
                    correlation_id=str(order.intent_id),
                    order_id=str(order.id),
                    intent_id=str(order.intent_id),
                    invoice_id=order.invoice_id,
                    nullifier=order.nullifier.value,
                    amount_micro_usdc=order.amount.micro_usdc,
                    chain_id=order.network.chain_id,
                )
            )
            await OutboxWriter(session).append(order.pull_events())

        # SC-2: the executor receives the order — the command path is derived, never passed.
        ack = await self._executor.execute(order)
        logger.info(
            "settlement.dispatch.executed",
            extra={
                "order_id": str(order.id),
                "intent_id": str(order.intent_id),
                "command_ref": ack.command_ref,
                "execution_id": ack.execution_id,
                "audit_uri": ack.audit_uri,
                "nullifier": order.nullifier.value,
            },
        )

        return DispatchPaymentResult(
            order_id=str(order.id),
            intent_id=str(order.intent_id),
            # No broadcast happened here (B-1); an order with a fabricated hash is worse than none.
            tx_hash=order.tx_hash,
            status=order.status.value,
            nullifier=order.nullifier.value,
            events=("SettlementOrdered",),
        )
