"""Settlement ports — the two adapters and the authority gate (frozen).

Canonical: .pi/architecture/modules/settlement.md#ports-infrastructure-adapters
Reference: docs/contracts/settlement-contract-freeze.md §2.8 (amended in §7 — two-phase `ChainGateway`)

Three ports, each keeping a foreign concern out of the domain:

`PaymentExecutor` — Rigorix `run_command`. It receives the **order**, not a params dict, so the command
path cannot be supplied by the caller (SC-2): the adapter can only call
`order.command_params()`, whose only source is the module constant.

`ChainGateway` — the chain, in **two phases**. `prepare` signs locally and returns a `SignedPayment`:
the hash is known and nothing has been broadcast, which is what makes SC-3's "persist the hash before
broadcast" expressible at all. `broadcast` sends those already-signed bytes. Signing and sending are
separated *because* the ordering, not because the chain wants two calls: one call that signs-and-sends
hands the caller a hash it could not have persisted first (this was blocker B-1). `is_nullifier_spent`
is the on-chain read that lets the app refuse a replay one layer earlier than the contract (SC-6).

`DeterminationGate` — Authority's allow/approved determination, **read now**. There is no
`cached_determination()`: a verdict issued at plan time is not a permission to dispatch (SC-1).

Ports are `Protocol`s, not ABCs: the domain needs the shape, and the adapters (`RigorixCommandAdapter`,
`Web3ChainGateway`, `AuthorityHttpAdapter`) live in `infrastructure/`. Protocol methods are
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

__all__ = ["ChainGateway", "CommandAck", "DeterminationGate", "PaymentExecutor", "SignedPayment"]


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
    #: Additive Phase-B evidence fields (defaulted, so the frozen three-field shape still holds).
    #: `execution_id` is the id the caller sent Rigorix — the settlement order id — and `audit_uri`
    #: is the host's audit trail for this run. Neither is a permission and neither is a payment; they
    #: exist so a dispatch can be reconciled with the governed-execution record it produced.
    execution_id: str = ""
    audit_uri: str = ""
    #: Additive: the **rendered** command text the host executed. `command_ref` is the settlement
    #: command's identity (`payments.dispatch`, SC-2) and is what evidence keys on; since the two-phase
    #: port that identity resolves to `payments.broadcast --raw-tx <hex>`, so the audit record has to
    #: name both — a reader must be able to see exactly which bytes the governed step sent.
    command_text: str = ""


@dataclass(frozen=True, slots=True)
class SignedPayment:
    """A signed `pay(...)` transaction whose hash is known and which has **not** been broadcast (SC-3).

    `eth_account` returns the signed bytes and their hash from the same call, so the ordering SC-3
    requires is expressible: the use case persists `tx_hash`, and only then hands these exact bytes to
    the governed broadcaster. This type is the reason the port is two-phase — not a wallet limitation.

    `raw_transaction` is public by definition: a signature, never a secret. Anyone who sees it can send
    the identical transaction, and that is precisely why re-sending it is not a second payment — the
    account nonce and the on-chain nullifier are what make a payment once-only (SC-3, SC-5).
    """

    #: `0x`-prefixed 32-byte hash, derived locally at signing time — what SC-3 persists.
    tx_hash: str
    #: `0x`-hex of the signed transaction bytes. The only input the broadcaster accepts.
    raw_transaction: str


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
    """`PaymentRouter.sol` + receipt reads, split into sign-then-send (SC-3, SC-6, SC-7, SC-12)."""

    async def prepare(self, order: SettlementOrder) -> SignedPayment:
        """Sign the payment locally. The hash is known afterwards; **nothing has been broadcast**.

        The order is the only input: the calldata is built from `order.payee_address`, `order.amount`
        and `order.nullifier`, never from a caller-supplied blob (SC-2, SC-9).

        Raises:
            SecondTransactionRefused: `order.tx_hash` is already set. Signing again would take a new
                nonce and could pay twice (SC-3); the caller re-broadcasts and re-polls the existing
                hash instead.
            SettlementRefusal: the order requires the owner's EIP-712 signature, which the settlement
                key cannot produce (A-15) — the second lock is never silently downgraded.
            SettlementRefusal: any provider failure, including a node that rejects the simulated call
                (a spent nullifier, an amount over the signed cap). Nothing was broadcast.
        """
        ...

    async def broadcast(self, signed: SignedPayment) -> None:
        """Send already-signed bytes to the node. Safe to repeat, and never a second payment.

        Idempotent-*safe*, not idempotent: a node treats the same bytes as a replay of the very same
        transaction (same hash, same nonce), and the on-chain nullifier is what actually refuses a
        second payment (SC-5). Re-broadcasting the persisted bytes after a crash is therefore the
        correct recovery, and it can never create a second settlement.

        Raises:
            SettlementRefusal: the node refused the bytes (nothing was accepted); every provider
                failure is a refusal, never a bare exception.
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
