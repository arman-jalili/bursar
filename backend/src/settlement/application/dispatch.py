"""`DispatchPayment` — the write path that turns an allowed intent into a governed dispatch.

Canonical: .pi/architecture/modules/settlement.md#application-services
Reference: docs/contracts/settlement-contract-freeze.md §2.10 (SC-1, SC-2, SC-3, SC-5, SC-9)

This is the concrete `DispatchPayment` the frozen catalog names. It lives in the application layer
because that is where the freeze puts it: one unit of work per state change, one outbox append, no rule
of its own. Every rule below is a call into the aggregate or the domain services:

    SC-1  DeterminationGate is read live (no cache), then `SettlementOrder.order` refuses a verdict
          that does not permit dispatch — before anything is persisted.
    SC-2  The command path never appears here. The executor is handed the **order**; the adapter can
          only read `order.command_ref` / `order.command_params()`, whose only source is the module
          constant.
    SC-3  The payment is signed **first** (`ChainGateway.prepare`), the hash and the signed bytes are
          persisted on the order (`mark_signed`, status `SIGNED`), and only then does the governed step
          broadcast those bytes. The hash exists in the database before any node has seen it.
    SC-5  The nullifier is checked locally (and on-chain when a `ChainGateway` is installed) before the
          governed command runs; the store's unique constraint remains the last lock.
    SC-9  `prepare` receives the order and signs `order.amount`; the amount is never an argument.

The chain write, stated exactly
-------------------------------
Two phases, and the seam between them is the point:

    prepare(order)          signs locally. The hash is known; NOTHING has been broadcast.
    mark_signed(...)        persists the hash + the signed bytes            <- SC-3, for real
    persist + outbox        one transaction commits both
    executor.execute(order) the governed Rigorix step runs `payments.broadcast --raw-tx <hex>`
    mark_submitted(...)     the same hash, now accepted by the governed step

`DispatchPaymentResult.tx_hash` is the **prepared** hash, so a caller learns the hash of a transaction
that is at least signed even when the governed step refused. A refusal there is not a rollback: the
order keeps its hash, its bytes and the `SIGNED` status, which is a real state — "signed, not
broadcast". Recovery is re-broadcasting those same bytes (a node-level replay of one transaction, and
the on-chain nullifier is what refuses a second payment, SC-5), never a second dispatch: the intent
already has an order, so a replay returns `DuplicateSettlementBlocked` (SC-4).

Signing before the row is inserted is deliberate. If `prepare` refuses (owner signature required, a
spent nullifier the node reports at estimation, an unreachable node), nothing is persisted at all — an
`ORDERED` row would occupy the intent's only dispatch slot for a payment that was never signed.

What is *not* here: conclusion. A receipt is read once, as evidence, after the governed step; the
`PENDING`/`CONFIRMED`/`REVERTED` decision stays with `SettleOnce` (SC-6, SC-7), which is still not
implemented. Nothing in this service marks an order concluded.
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.authority.domain.ids import IntentId
from src.settlement.application.dto import DispatchPaymentCommand, DispatchPaymentResult
from src.settlement.application.services import DispatchPayment
from src.settlement.domain.errors import DuplicateSettlementBlocked, SettlementRefusal
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
from src.shared.domain.errors import ErrorCode
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
    """One dispatch: live authority → order → signed bytes → governed broadcast (SC-1, SC-2, SC-3)."""

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
        """Create the order, sign it, persist its hash, then let the governed step broadcast it.

        Raises:
            SettlementRefusal: no `ChainGateway` is composed, so nothing could be signed and the
                governed step would have nothing to broadcast (refused before anything is persisted).
            SettlementRefusal: the Authority reads failed closed (SC-1), the determination does not
                permit dispatch (SC-1), the invoice's nullifier is spent (SC-5), an order already
                exists for this intent (SC-4), signing refused (a spent nullifier the node reports at
                estimation, or an order that requires the owner's signature — A-15), or Rigorix
                refused / did not answer (SC-2). In the first four cases nothing was broadcast and
                nothing was persisted; in the last two the order keeps its persisted hash and stays
                `SIGNED`.
        """
        intent_id = IntentId(command.intent_id)

        if self._chain is None:
            # A dispatch *is* the broadcast of bytes this service signed. Without a gateway there is
            # nothing to sign, so there is no honest way to run the governed step — and persisting an
            # order first would occupy the intent's only dispatch slot (SC-4) for a payment that can
            # never be made.
            raise SettlementRefusal(
                ErrorCode.CONFLICT,
                "No chain gateway is composed in this process, so a dispatch could be signed but "
                "never broadcast; refusing before anything is persisted.",
                details={"reason": "no_chain_gateway"},
            )

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
                # dispatch — and an existing `SIGNED` order is recovered by re-broadcasting its own
                # bytes, not by signing a new transaction.
                raise DuplicateSettlementBlocked(
                    nullifier=existing.nullifier.value, order_id=str(existing.id)
                )

            policy = NullifierPolicy()
            policy.guard_unspent(
                order.nullifier,
                already_spent=await SqlNullifierRepository(session).is_spent(order.nullifier),
            )
            policy.guard_unspent(
                order.nullifier,
                already_spent=await self._chain.is_nullifier_spent(order.nullifier),
            )

            # SC-3, first half: local signing. The hash exists afterwards; nothing has been broadcast.
            signed = await self._chain.prepare(order)
            order.mark_signed(signed.tx_hash, signed.raw_transaction, order.amount)

            # The row is inserted *with* the hash and the signed bytes, so the write-ahead record is
            # durable in the same transaction that creates the order.
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
        # Commit point 1: the hash and the signed bytes are durable. Only now may anything broadcast.

        # SC-2: the executor receives the order — the command path is derived, never passed, and the
        # command it renders carries this order's already-signed bytes.
        ack = await self._executor.execute(order)
        logger.info(
            "settlement.dispatch.broadcast",
            extra={
                "order_id": str(order.id),
                "intent_id": str(order.intent_id),
                "command_ref": ack.command_ref,
                "command_text": ack.command_text,
                "execution_id": ack.execution_id,
                "audit_uri": ack.audit_uri,
                "nullifier": order.nullifier.value,
                "tx_hash": signed.tx_hash,
            },
        )

        # Commit point 2: the same hash, now accepted by the governed step.
        async with session_scope(self._session_factory) as session:
            order.mark_submitted(signed.tx_hash, order.amount)
            await SqlSettlementOrderRepository(session).save(order)
            await OutboxWriter(session).append(order.pull_events())

        await self._observe_receipt(order)

        return DispatchPaymentResult(
            order_id=str(order.id),
            intent_id=str(order.intent_id),
            # The prepared hash: a caller learns the hash of a transaction that is at least signed,
            # even when the governed step refused. It is never invented (SC-3).
            tx_hash=order.tx_hash,
            status=order.status.value,
            nullifier=order.nullifier.value,
            events=("SettlementOrdered", "SettlementSubmitted"),
        )

    async def _observe_receipt(self, order: SettlementOrder) -> None:
        """Read the receipt once, for evidence. This is not a conclusion (SC-7 belongs to `SettleOnce`).

        A read failure is logged and swallowed on purpose: the payment was signed and the governed step
        accepted it, so reporting an error here would tell the caller a settlement failed because a
        node was slow. The persisted hash is what an operator re-polls.
        """
        assert self._chain is not None  # guarded in `execute`
        if order.tx_hash is None:  # pragma: no cover - `mark_submitted` guarantees the hash
            return
        try:
            receipt = await self._chain.receipt(order.tx_hash)
        except SettlementRefusal as refused:
            logger.warning(
                "settlement.dispatch.receipt_unreadable",
                extra={"order_id": str(order.id), "reason": str(refused)},
            )
            return
        logger.info(
            "settlement.dispatch.receipt",
            extra={
                "order_id": str(order.id),
                "tx_hash": order.tx_hash,
                "mined": receipt is not None,
                "status": receipt.status.value if receipt is not None else "",
                "block_number": receipt.block_number if receipt is not None else 0,
                "confirmations": receipt.confirmations if receipt is not None else 0,
            },
        )
