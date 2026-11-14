"""The chain adapters — `PaymentRouter.sol` over web3 (SC-3, SC-6, SC-7, SC-10, SC-11).

Canonical: `.pi/architecture/modules/settlement.md#ports-infrastructure-adapters`
Reference: `docs/contracts/settlement-contract-freeze.md` §2.8 (`ChainGateway`)

`Web3ChainGateway` is the `ChainGateway` port against a real EVM: it signs a `PaymentRouter.pay` call
with the settlement key, reads receipts with the network's confirmation depth, and reads
`spentNullifiers` so the application can refuse a replay one layer before the contract does.

`abi.py` carries the router ABI. It is not a build artifact: a test recompiles the Solidity and asserts
the constant equals the compiler's ABI, so the Python adapter and the contract cannot drift silently.

Nothing in this package signs for a *payment* the frozen contract does not already describe: `submit`
builds the call from `SettlementOrder` alone (SC-3, SC-9), never from a caller-supplied calldata blob.
"""

from __future__ import annotations

from src.settlement.infrastructure.chain.abi import ROUTER_ABI, ROUTER_ERROR_SELECTORS
from src.settlement.infrastructure.chain.web3_gateway import (
    Web3ChainGateway,
    named_contract_error,
    revert_payload,
)

__all__ = [
    "ROUTER_ABI",
    "ROUTER_ERROR_SELECTORS",
    "Web3ChainGateway",
    "named_contract_error",
    "revert_payload",
]
