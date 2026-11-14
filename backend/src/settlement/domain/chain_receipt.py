"""ChainReceipt — the chain proof for one order, and what it cost (frozen).

Canonical: .pi/architecture/modules/settlement.md#components
Reference: docs/contracts/settlement-contract-freeze.md (SC-6, SC-7, SC-10)

    SC-7   finality is a property of the network's required confirmations
    SC-10  every receipt records gas_used, gas_price and a fee estimate; CostSummary derives from
           receipts only (ADR-006)

`ReceiptStatus` distinguishes "mined and successful" from "final": a receipt can be `SUCCESS` with zero
confirmations, and concluding it then would commit the cap on a transaction a reorg can still remove.
That is why `is_final(confirmations_required)` takes the number instead of trusting a flag: the receipt
cannot know the network's policy, and the network value is frozen (SC-11).

The cost fields are non-optional on purpose. A receipt with `gas_used=None` would make `CostSummary`
either wrong or silently partial; ADR-006 says the summary must never be a competing balance, and it
cannot be derived at all from receipts that omit their cost. A missing cost is therefore a refusal
(`ReceiptCostMissing`), not a zero.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.settlement.domain.errors import ReceiptCostMissing
from src.settlement.domain.ids import OrderId, ReceiptId
from src.settlement.domain.values import ReceiptStatus
from src.shared.domain.money import Money

__all__ = ["ChainReceipt"]


@dataclass(frozen=True, slots=True)
class ChainReceipt:
    """One immutable chain fact: tx hash, block, confirmations, status and cost (SC-6, SC-7, SC-10)."""

    id: ReceiptId
    order_id: OrderId
    tx_hash: str
    block_number: int
    confirmations: int
    status: ReceiptStatus
    #: Gas consumed by the transaction. Required: a receipt without it cannot be costed (SC-10).
    gas_used: int
    #: Effective gas price in wei, as a decimal string — wei does not fit a JS number safely.
    gas_price: str
    #: Fee estimate in USDC, derived from gas_used x gas_price and the network's rate (SC-10).
    fee_usdc_estimate: Money
    #: True only for the `anchor` write, so anchoring is never mistaken for a payment (ADR-006).
    is_anchor: bool = False
    #: The contract's revert reason when `status` is `REVERTED` — evidence, never a retry hint (SC-6).
    revert_reason: str = ""

    def __post_init__(self) -> None:
        """Refuse a receipt without gas, gas price or a fee estimate (SC-10).

        Raises:
            ReceiptCostMissing: any cost field is absent, negative or unparseable. A missing cost is a
                refusal, not a zero: `CostSummary` must never under-report what the chain charged.
        """
        if (
            isinstance(self.gas_used, bool)
            or not isinstance(self.gas_used, int)
            or self.gas_used < 0
        ):
            raise ReceiptCostMissing("gas_used")
        if not isinstance(self.gas_price, str) or not self.gas_price.strip():
            raise ReceiptCostMissing("gas_price")
        try:
            if int(self.gas_price, 10) < 0:
                raise ReceiptCostMissing("gas_price")
        except ValueError as exc:
            raise ReceiptCostMissing("gas_price") from exc
        if not isinstance(self.fee_usdc_estimate, Money) or self.fee_usdc_estimate.micro_usdc < 0:
            raise ReceiptCostMissing("fee_usdc_estimate")
        if self.confirmations < 0:
            raise ReceiptCostMissing("confirmations")

    def is_final(self, confirmations_required: int) -> bool:
        """True when the transaction is successful and has the network's required confirmations (SC-7).

        A reverted transaction is never final-as-success: it is concluded as a refusal by the caller.
        """
        return self.confirmed and self.confirmations >= confirmations_required

    @property
    def confirmed(self) -> bool:
        """True when the chain accepted the transaction (status `SUCCESS`), regardless of depth (SC-7)."""
        return self.status is ReceiptStatus.SUCCESS
