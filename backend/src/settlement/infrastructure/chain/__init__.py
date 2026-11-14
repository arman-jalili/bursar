"""The chain adapters — `PaymentRouter.sol` over web3 (SC-3, SC-6, SC-7, SC-10, SC-11).

Canonical: `.pi/architecture/modules/settlement.md#ports-infrastructure-adapters`
Reference: `docs/contracts/settlement-contract-freeze.md` §2.8 (`ChainGateway`)

`Web3ChainGateway` is the `ChainGateway` port against a real EVM: `prepare` signs a `PaymentRouter.pay`
call locally (the tx hash is known, nothing is sent), `broadcast` sends those exact signed bytes,
`receipt` reads the outcome with the network's confirmation depth, and `spentNullifiers` lets the
application refuse a replay one layer before the contract does.

`abi.py` carries the router ABI. It is not a build artifact: a test recompiles the Solidity and asserts
the constant equals the compiler's ABI, so the Python adapter and the contract cannot drift silently.

`broadcast_cli.py` is the governed step's body (`payments.broadcast --raw-tx <hex>`). It sends bytes and
nothing else — no database, no order lookup, no network re-derivation, no signing — because every one of
those would be a second path to a payment.

Nothing in this package signs for a *payment* the frozen contract does not already describe: `prepare`
builds the call from `SettlementOrder` alone (SC-3, SC-9), never from a caller-supplied calldata blob.
"""

from __future__ import annotations

from src.settlement.infrastructure.chain.abi import ROUTER_ABI, ROUTER_ERROR_SELECTORS
from src.settlement.infrastructure.chain.broadcast_cli import broadcast_raw_transaction
from src.settlement.infrastructure.chain.web3_gateway import (
    Web3ChainGateway,
    named_contract_error,
    revert_payload,
)

__all__ = [
    "ROUTER_ABI",
    "ROUTER_ERROR_SELECTORS",
    "Web3ChainGateway",
    "broadcast_raw_transaction",
    "named_contract_error",
    "revert_payload",
]
