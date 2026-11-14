"""The `PaymentRouter.sol` ABI — the one copy the Python adapter calls through.

Canonical: `docs/architecture/modules/settlement.md#ports-infrastructure-adapters`
Reference: `docs/contracts/settlement-contract-freeze.md` §2.8 (`ChainGateway`), SC-11

Why the ABI lives in Python rather than in a build artifact:

* `forge` is not installed in this environment (foundry.toml is pinned for the machines that have it),
  so a JSON artifact under `out/` is not something this repository can regenerate on every machine.
  An adapter that only works after a manual build step is an adapter that silently breaks.
* The ABI is a *contract surface*, not a build output: the gateway calls `pay`, `anchor`,
  `spentNullifiers` and `paymentDigest`, and decodes `Anchored` plus the named errors. Those entries
  change only when the contract's interface changes — which is a contract change, not a build.
* The drift risk ADR-007 names ("a hand-kept second list is how the two drift") is covered by a test,
  not by hope: `tests/unit/settlement/chain/test_payment_router_contract.py` compiles the real
  `contracts/src/PaymentRouter.sol` with solc 0.8.24 and asserts this constant equals the compiled
  ABI exactly. Adding, renaming or reordering a function/error/event fails that test until the two
  are reconciled in one commit.

`ROUTER_ERROR_SELECTORS` is derived from the ABI's `error` entries, so a refused transaction is mapped
to its *named* error (`NullifierSpent`, `OwnerSignatureInvalid`, …) instead of a reworded string.
"""

from __future__ import annotations

from typing import Any, Final

from eth_utils import keccak

__all__ = ["ROUTER_ABI", "ROUTER_ERROR_SELECTORS"]

#: The compiled `PaymentRouter` ABI (solc 0.8.24, optimizer 200 runs, evm_version paris).
ROUTER_ABI: Final[list[dict[str, Any]]] = [
    {
        "inputs": [
            {
                "internalType": "address",
                "name": "owner_",
                "type": "address",
            },
            {
                "internalType": "address",
                "name": "usdc_",
                "type": "address",
            },
        ],
        "stateMutability": "nonpayable",
        "type": "constructor",
    },
    {
        "inputs": [
            {
                "internalType": "uint256",
                "name": "amount",
                "type": "uint256",
            },
        ],
        "name": "AmountNotPositive",
        "type": "error",
    },
    {
        "inputs": [
            {
                "internalType": "bytes32",
                "name": "nullifier",
                "type": "bytes32",
            },
        ],
        "name": "NullifierSpent",
        "type": "error",
    },
    {
        "inputs": [
            {
                "internalType": "address",
                "name": "recovered",
                "type": "address",
            },
            {
                "internalType": "address",
                "name": "owner",
                "type": "address",
            },
        ],
        "name": "OwnerSignatureInvalid",
        "type": "error",
    },
    {
        "inputs": [
            {
                "internalType": "bytes32",
                "name": "orderId",
                "type": "bytes32",
            },
        ],
        "name": "OwnerSignatureRequired",
        "type": "error",
    },
    {
        "inputs": [
            {
                "internalType": "address",
                "name": "payee",
                "type": "address",
            },
            {
                "internalType": "uint256",
                "name": "amount",
                "type": "uint256",
            },
        ],
        "name": "TransferFailed",
        "type": "error",
    },
    {
        "inputs": [
            {
                "internalType": "string",
                "name": "field",
                "type": "string",
            },
        ],
        "name": "ZeroAddress",
        "type": "error",
    },
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": True,
                "internalType": "bytes32",
                "name": "orderId",
                "type": "bytes32",
            },
            {
                "indexed": True,
                "internalType": "bytes32",
                "name": "nullifier",
                "type": "bytes32",
            },
            {
                "indexed": False,
                "internalType": "bytes32",
                "name": "txRef",
                "type": "bytes32",
            },
        ],
        "name": "Anchored",
        "type": "event",
    },
    {
        "inputs": [],
        "name": "DOMAIN_NAME_HASH",
        "outputs": [
            {
                "internalType": "bytes32",
                "name": "",
                "type": "bytes32",
            },
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "DOMAIN_VERSION_HASH",
        "outputs": [
            {
                "internalType": "bytes32",
                "name": "",
                "type": "bytes32",
            },
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "EIP712_DOMAIN_TYPEHASH",
        "outputs": [
            {
                "internalType": "bytes32",
                "name": "",
                "type": "bytes32",
            },
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "PAYMENT_TYPEHASH",
        "outputs": [
            {
                "internalType": "bytes32",
                "name": "",
                "type": "bytes32",
            },
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {
                "internalType": "bytes32",
                "name": "anchoredHash",
                "type": "bytes32",
            },
        ],
        "name": "anchor",
        "outputs": [
            {
                "internalType": "bytes32",
                "name": "",
                "type": "bytes32",
            },
        ],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "domainSeparator",
        "outputs": [
            {
                "internalType": "bytes32",
                "name": "",
                "type": "bytes32",
            },
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {
                "internalType": "bytes32",
                "name": "orderId",
                "type": "bytes32",
            },
            {
                "internalType": "bytes32",
                "name": "nullifier",
                "type": "bytes32",
            },
            {
                "internalType": "address",
                "name": "payer",
                "type": "address",
            },
            {
                "internalType": "address",
                "name": "payee",
                "type": "address",
            },
            {
                "internalType": "uint256",
                "name": "amount",
                "type": "uint256",
            },
        ],
        "name": "hashPayment",
        "outputs": [
            {
                "internalType": "bytes32",
                "name": "structHash",
                "type": "bytes32",
            },
            {
                "internalType": "bytes32",
                "name": "digest",
                "type": "bytes32",
            },
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "owner",
        "outputs": [
            {
                "internalType": "address",
                "name": "",
                "type": "address",
            },
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {
                "internalType": "bytes32",
                "name": "orderId",
                "type": "bytes32",
            },
            {
                "internalType": "bytes32",
                "name": "nullifier",
                "type": "bytes32",
            },
            {
                "internalType": "address",
                "name": "payee",
                "type": "address",
            },
            {
                "internalType": "uint256",
                "name": "amount",
                "type": "uint256",
            },
            {
                "internalType": "bool",
                "name": "requiresOwnerSignature",
                "type": "bool",
            },
            {
                "internalType": "bytes",
                "name": "ownerSignature",
                "type": "bytes",
            },
        ],
        "name": "pay",
        "outputs": [
            {
                "internalType": "bytes32",
                "name": "txRef",
                "type": "bytes32",
            },
        ],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {
                "internalType": "bytes32",
                "name": "orderId",
                "type": "bytes32",
            },
            {
                "internalType": "bytes32",
                "name": "nullifier",
                "type": "bytes32",
            },
            {
                "internalType": "address",
                "name": "payer",
                "type": "address",
            },
            {
                "internalType": "address",
                "name": "payee",
                "type": "address",
            },
            {
                "internalType": "uint256",
                "name": "amount",
                "type": "uint256",
            },
        ],
        "name": "paymentDigest",
        "outputs": [
            {
                "internalType": "bytes32",
                "name": "",
                "type": "bytes32",
            },
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {
                "internalType": "bytes32",
                "name": "nullifier",
                "type": "bytes32",
            },
        ],
        "name": "spentNullifiers",
        "outputs": [
            {
                "internalType": "bool",
                "name": "",
                "type": "bool",
            },
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "usdc",
        "outputs": [
            {
                "internalType": "contract IERC20",
                "name": "",
                "type": "address",
            },
        ],
        "stateMutability": "view",
        "type": "function",
    },
]


def _error_signature(entry: dict[str, Any]) -> str:
    """`Name(type1,type2)` — the shape Solidity hashes to produce an error selector."""
    inputs = ",".join(argument["type"] for argument in entry.get("inputs", []))
    return f"{entry['name']}({inputs})"


#: `0x`-prefixed 4-byte selector -> the contract's named error. Used to turn a revert into a refusal.
ROUTER_ERROR_SELECTORS: Final[dict[str, str]] = {
    "0x" + keccak(text=_error_signature(entry))[:4].hex(): str(entry["name"])
    for entry in ROUTER_ABI
    if entry.get("type") == "error"
}
