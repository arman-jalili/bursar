"""SC-10 — every receipt records gas, gas price and a fee estimate; cost derives from receipts only.

Canonical: docs/contracts/settlement-contract-freeze.md §1 (SC-10)
Reference: docs/architecture/decisions/ADR-006-cost-tracking-usage-metering.md

Defends module AC #10. Two rules, both refusals rather than conventions:

* a receipt without a cost is **not a receipt** (`ReceiptCostMissing`) — accepting it would make
  `CostSummary` under-report what the chain charged;
* `CostSummary` is derived from receipts only, so it can never become a competing balance.

Anchors are receipts too (`is_anchor`), which is why the cost fields are required there as well: the
anchor write costs gas, and ADR-006 counts it.
"""

from __future__ import annotations

import pytest
from src.settlement.domain.chain_receipt import ChainReceipt
from src.settlement.domain.errors import ReceiptCostMissing
from src.settlement.domain.ids import OrderId, ReceiptId
from src.settlement.domain.values import ReceiptStatus
from src.shared.domain.money import Money


def _receipt(**overrides: object) -> ChainReceipt:
    fields: dict[str, object] = {
        "id": ReceiptId("r-1"),
        "order_id": OrderId("o-1"),
        "tx_hash": "0x" + "ef" * 32,
        "block_number": 7,
        "confirmations": 1,
        "status": ReceiptStatus.SUCCESS,
        "gas_used": 51_000,
        "gas_price": "1000000000",
        "fee_usdc_estimate": Money(51),
    }
    fields.update(overrides)
    return ChainReceipt(**fields)  # type: ignore[arg-type]


class TestReceiptCost:
    def test_a_receipt_without_gas_used_is_refused(self) -> None:
        """SC-10 / AC-10: gas is the first factor of the fee; without it the cost is unknown."""
        with pytest.raises(ReceiptCostMissing):
            _receipt(gas_used=None)

    def test_a_receipt_without_a_gas_price_is_refused(self) -> None:
        """SC-10 / AC-10: a fee estimated from no price is an invented number."""
        with pytest.raises(ReceiptCostMissing):
            _receipt(gas_price="")

    def test_a_receipt_without_a_fee_estimate_is_refused(self) -> None:
        """SC-10 / AC-10: the estimate is what `CostSummary` sums; absent is not zero."""
        with pytest.raises(ReceiptCostMissing):
            _receipt(fee_usdc_estimate=None)

    def test_a_receipt_with_all_costs_is_accepted(self) -> None:
        """SC-10 / AC-10: the honest receipt passes and exposes every cost field."""
        receipt = _receipt()

        assert receipt.gas_used == 51_000
        assert receipt.fee_usdc_estimate.micro_usdc == 51

    def test_an_anchor_receipt_is_costed_too(self) -> None:
        """SC-10 / AC-10: ADR-006 counts the anchor write, so it cannot be exempt from cost."""
        receipt = _receipt(is_anchor=True)

        assert receipt.fee_usdc_estimate.micro_usdc > 0
