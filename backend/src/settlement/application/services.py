"""Settlement application services — the catalog names, frozen (FR-019, FR-021).

Canonical: .pi/architecture/modules/settlement.md#application-services
Reference: docs/contracts/settlement-contract-freeze.md §2.10

    DispatchPayment  FR-019  sign the allowed order locally, persist the hash, then broadcast it
    SettleOnce       FR-021  re-poll the same hash, enforce finality, conclude once, publish the outcome
    GetReceipt               read one order's receipt (SC-10)
    ListOrders               read orders for the console
    AnchorHash               write an evidence hash on-chain (used by Evidence)
    CostSummary              derive cost from receipts only (ADR-006, SC-10)

Names come from the exploration use-cases pass and are not negotiable: they are how the console, the
agent and the evidence trail refer to these use cases.

Each implementation must open exactly one `session_scope` **per state change** and append the drained
events to `settlement_outbox` in that same transaction (ADR-003). Two orderings are part of the
contract, not an implementation detail:

1. **Persist the tx hash before broadcast** (SC-3). The use case signs locally (`ChainGateway.prepare`,
   hash known, nothing sent), writes `mark_signed` — hash *and* signed bytes — in a transaction that
   commits, and only then runs the governed broadcast. A crash before the broadcast re-sends the same
   bytes; it never signs a second transaction.
2. **A revert ends the use case** (SC-6, SC-8). `SettleOnce` records `SettlementReverted` and returns;
   there is no retry branch, because a retry branch is the timeout double-pay.

Nothing business-shaped lives here — the rules are on the aggregate and the two domain services, which
is why these classes have no logic even once Phase B lands.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.settlement.application.dto import (
    AnchorHashCommand,
    AnchorHashResult,
    CostSummaryQuery,
    CostSummaryView,
    DispatchPaymentCommand,
    DispatchPaymentResult,
    ListOrdersQuery,
    OrderView,
    ReceiptView,
    SettleOnceCommand,
    SettleOnceResult,
)

__all__ = [
    "AnchorHash",
    "CostSummary",
    "DispatchPayment",
    "GetReceipt",
    "ListOrders",
    "SettleOnce",
]


class DispatchPayment(ABC):
    """Turn an allowed intent into a submitted payment — once (FR-019)."""

    @abstractmethod
    async def execute(self, command: DispatchPaymentCommand) -> DispatchPaymentResult:
        """Create the order, sign it, persist its hash, then broadcast through the governed step.

        Raises:
            DispatchWithoutAuthority: no determination permits dispatch (SC-1).
            DuplicateSettlementBlocked: the invoice's nullifier is already spent (SC-5), or the intent
                already has an order (SC-4).
            AmountIntegrityViolation: the amount handed to the chain differs from the signed amount
                (SC-9) — refused before anything is broadcast.
            SecondTransactionRefused: the order already has a hash (SC-3).
        """
        raise NotImplementedError("SC-1 — see module doc")


class SettleOnce(ABC):
    """Reconcile one order exactly once: finality, conclusion, outbox (FR-021)."""

    @abstractmethod
    async def execute(self, command: SettleOnceCommand) -> SettleOnceResult:
        """Poll the order's persisted hash and conclude it if it is final.

        Raises:
            DuplicateSettlementBlocked: the nullifier is spent on-chain before this order spent it
                (SC-6, scenario 6 bypass path).
            OrderAlreadyConcluded: the order is terminal; a second conclusion is a bug (SC-4).
            SettlementNotFinal: the receipt exists below the confirmation threshold (SC-7).
        """
        raise NotImplementedError("SC-5 — see module doc")


class GetReceipt(ABC):
    """Read the chain proof for one order (SC-10)."""

    @abstractmethod
    async def execute(self, order_id: str) -> ReceiptView:
        """Return the receipt; the order must have one.

        Raises:
            NotFoundError: no receipt exists for that order.
        """
        raise NotImplementedError("SC-10 — see module doc")


class ListOrders(ABC):
    """Read orders for the console."""

    @abstractmethod
    async def execute(self, query: ListOrdersQuery) -> tuple[OrderView, ...]:
        """Return orders matching the query, newest first."""
        raise NotImplementedError("SC-4 — see module doc")


class AnchorHash(ABC):
    """Anchor an evidence hash on-chain (ADR-006)."""

    @abstractmethod
    async def execute(self, command: AnchorHashCommand) -> AnchorHashResult:
        """Write the hash and return the anchor transaction.

        Raises:
            ValidationError: the hash is not a 32-byte hex value.
        """
        raise NotImplementedError("SC-10 — see module doc")


class CostSummary(ABC):
    """Derive cost from receipts only — never a competing balance (ADR-006, SC-10)."""

    @abstractmethod
    async def execute(self, query: CostSummaryQuery) -> CostSummaryView:
        """Sum the day's receipts; a receipt without cost is impossible by construction (SC-10)."""
        raise NotImplementedError("SC-10 — see module doc")
