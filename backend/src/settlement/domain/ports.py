"""Settlement ports — the two adapters and the authority gate (frozen).

Canonical: .pi/architecture/modules/settlement.md#ports-infrastructure-adapters
Reference: docs/contracts/settlement-contract-freeze.md §2.8

Three ports, each keeping a foreign concern out of the domain:

`PaymentExecutor` — Rigorix `run_command`. It receives the **order**, not a params dict, so the command
path cannot be supplied by the caller (SC-2): the adapter can only call
`order.command_params()`, whose only source is the module constant.

`ChainGateway` — the chain. `submit` returns a tx hash; the caller persists it before broadcast
(SC-3), which is why this method is *not* "pay": submission and the write-ahead record are separate
steps in the use case's transaction. `is_nullifier_spent` is the on-chain read that lets the app refuse
a replay one layer earlier than the contract (SC-6).

`DeterminationGate` — Authority's allow/approved determination, **read now**. There is no
`cached_determination()`: a verdict issued at plan time is not a permission to dispatch (SC-1).

Ports are `Protocol`s, not ABCs: the domain needs the shape, and the adapters (`RigorixCommandAdapter`,
`Web3RouterAdapter`, `AuthorityHttpAdapter`) live in `infrastructure/` in Phase B. Protocol methods are
declarations — `...`, not a body — so there is no logic in the freeze. None of these ports carries
transaction control; the unit of work is the application layer's (ADR-002).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.authority.domain.ids import IntentId
from src.settlement.domain.chain_receipt import ChainReceipt
from src.settlement.domain.settlement_order import SettlementOrder
from src.settlement.domain.values import Nullifier
from src.settlement.domain.views import DeterminationView

__all__ = ["ChainGateway", "CommandAck", "DeterminationGate", "PaymentExecutor"]


@dataclass(frozen=True, slots=True)
class CommandAck:
    """What `run_command` tells us: which command ran and whether its precondition held.

    `accepted` is not a payment — it is the Rigorix gate's answer. A rejection here means nothing was
    broadcast and no tx hash exists (SC-1 at the framework layer, SC-3 at ours).
    """

    command_ref: str
    accepted: bool
    #: The framework's precondition string, kept for evidence; empty when accepted.
    precondition: str = ""


class PaymentExecutor(Protocol):
    """Rigorix `run_command` port (SC-2)."""

    async def execute(self, order: SettlementOrder) -> CommandAck:
        """Run the fixed dispatch command for this order.

        Implementations MUST derive the command path from `order.command_ref` / `command_params()`;
        accepting a path from anywhere else defeats SC-2.

        Raises:
            SettlementRefusal: the framework refused the precondition (nothing was dispatched).
        """
        ...


class ChainGateway(Protocol):
    """`PaymentRouter.sol` + receipt reads (SC-3, SC-6, SC-7, SC-12)."""

    async def submit(self, order: SettlementOrder) -> str:
        """Broadcast the payment and return the tx hash.

        The caller has already persisted the hash it is about to receive (SC-3); this method must not
        sign a second transaction for an order that has one.

        Raises:
            SettlementRefusal: the node refuses to accept the transaction (nothing was broadcast).
        """
        ...

    async def receipt(self, tx_hash: str) -> ChainReceipt | None:
        """Read the receipt for a hash, or None while it is not mined. Never invents a hash."""
        ...

    async def is_nullifier_spent(self, nullifier: Nullifier) -> bool:
        """Read `PaymentRouter.spentNullifiers` — the on-chain copy of SC-5 (SC-6)."""
        ...

    async def anchor(self, anchored_hash: str) -> str:
        """Write an evidence/envelope hash on-chain and return the anchor tx hash (ADR-006)."""
        ...


class DeterminationGate(Protocol):
    """Authority's dispatch gate, read at dispatch time (SC-1)."""

    async def determination_for(self, intent_id: IntentId) -> DeterminationView:
        """Return the determination in force **now** for this intent.

        Implementations MUST NOT cache a plan-time verdict: scenario 3 (a payee frozen between plan and
        dispatch) passes only because this read is live (SC-1).

        Raises:
            NotFoundError: no determination exists — which is a refusal to dispatch, not a default.
        """
        ...
