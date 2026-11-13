"""Settlement commands and results (frozen) — the shape every caller codes against.

Canonical: .pi/architecture/modules/settlement.md#application-services
Reference: docs/contracts/settlement-contract-freeze.md §2.9

Two decisions encoded here:

* **`DispatchPaymentCommand` carries an `intent_id` and an optional idempotency key — and nothing
  else.** There is no `command`, `command_path`, `payee_address`, `amount` or `network` field, so a
  transport cannot smuggle one: the type is the first line of SC-2. The network is resolved by the
  application service from configuration (SC-11), not supplied by the caller.
* Amounts are integer micro-units (`amount_micro_usdc`, `fee_micro_usdc`) per ADR-002; tx hashes and
  nullifiers are strings. No DTO carries an address it could have been handed at request time.

`ReceiptView` exposes gas and fee because the receipt is the only cost record (ADR-006, SC-10);
`CostSummaryView` is a *derived* projection of those rows — never a stored balance.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "AnchorHashCommand",
    "AnchorHashResult",
    "CostSummaryQuery",
    "CostSummaryView",
    "DispatchPaymentCommand",
    "DispatchPaymentResult",
    "ListOrdersQuery",
    "OrderView",
    "ReceiptView",
    "SettleOnceCommand",
    "SettleOnceResult",
]


@dataclass(frozen=True, slots=True)
class DispatchPaymentCommand:
    """Dispatch one allowed intent (FR-019). The only field is the intent; there is no path field."""

    intent_id: str
    #: Retry-safe dedupe key from the transport (ADR-004). Never used as an id.
    idempotency_key: str = ""


@dataclass(frozen=True, slots=True)
class DispatchPaymentResult:
    order_id: str
    intent_id: str
    #: `None` only if the framework precondition refused after the order was persisted — in which case
    #: the order is `ABANDONED`, never re-signed (SC-3, SC-8).
    tx_hash: str | None
    status: str
    nullifier: str = ""
    events: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SettleOnceCommand:
    """Reconcile one order exactly once (FR-021)."""

    order_id: str


@dataclass(frozen=True, slots=True)
class SettleOnceResult:
    order_id: str
    status: str
    confirmations: int = 0
    #: True only when the receipt crossed finality and the cap may be committed (SC-7).
    cap_committed: bool = False
    events: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OrderView:
    """An order as the API exposes it. Status plus the write-ahead hash (SC-3)."""

    order_id: str
    intent_id: str
    invoice_id: str
    status: str
    amount_micro_usdc: int
    nullifier: str
    tx_hash: str | None = None
    chain_id: int = 0


@dataclass(frozen=True, slots=True)
class ReceiptView:
    """The chain proof plus its cost (SC-7, SC-10)."""

    order_id: str
    tx_hash: str
    block_number: int
    confirmations: int
    status: str
    gas_used: int
    gas_price: str
    fee_micro_usdc: int
    is_anchor: bool = False
    revert_reason: str = ""


@dataclass(frozen=True, slots=True)
class ListOrdersQuery:
    status: str = ""
    limit: int = 50


@dataclass(frozen=True, slots=True)
class CostSummaryQuery:
    """Costs for one UTC day; derived from receipts, never stored (ADR-006)."""

    day_iso: str


@dataclass(frozen=True, slots=True)
class CostSummaryView:
    day_iso: str
    receipt_count: int
    total_fee_micro_usdc: int
    by_network: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AnchorHashCommand:
    """Anchor one evidence/envelope hash on-chain (used by Evidence)."""

    hash: str
    correlation_id: str = ""


@dataclass(frozen=True, slots=True)
class AnchorHashResult:
    anchor_tx: str
    anchored_hash: str
