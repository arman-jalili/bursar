"""Settlement transport schemas — the frozen field names, in one place.

Canonical: docs/contracts/settlement-contract-freeze.md §2.10, §2.11
Reference: .pi/architecture/modules/settlement.md#api-endpoints

Amounts are integer micro-USDC and tx hashes/nullifiers are strings, matching the frozen DTOs exactly:
the console is built against these names, so a rename here is a contract change. There is deliberately
**no** `command`, `command_path`, `payee_address` or `amount` field on any request body — the dispatch
request carries an intent id and an idempotency key and nothing else (SC-2).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = [
    "CostSummaryResponse",
    "NullifierStatusResponse",
    "OrderListResponse",
    "OrderResponse",
    "ReceiptListResponse",
    "ReceiptResponse",
]


class OrderResponse(BaseModel):
    """One order as the API exposes it: status plus the write-ahead hash (SC-3)."""

    order_id: str
    intent_id: str
    invoice_id: str
    status: str
    amount_micro_usdc: int
    nullifier: str
    tx_hash: str | None = None
    chain_id: int = 0


class OrderListResponse(BaseModel):
    orders: list[OrderResponse]
    count: int


class ReceiptResponse(BaseModel):
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


class CostSummaryResponse(BaseModel):
    """A derived projection of receipt rows — never a stored balance (ADR-006)."""

    day_iso: str
    receipt_count: int
    total_fee_micro_usdc: int
    by_network: dict[str, int] = Field(default_factory=dict)


class ReceiptListResponse(BaseModel):
    receipts: list[ReceiptResponse]
    cost: CostSummaryResponse


class NullifierStatusResponse(BaseModel):
    """`{spent, order_id}` — the local copy of the on-chain marker (SC-5)."""

    nullifier: str
    spent: bool
    order_id: str | None = None
