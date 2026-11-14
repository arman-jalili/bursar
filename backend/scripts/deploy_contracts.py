"""Deploy the demo chain: TestUsdc + PaymentRouter, fund the operator, publish addresses.

Run inside the backend image (it has py-solc-x and web3):

    BURSAR_RPC_URL=http://anvil:8545 python scripts/deploy_contracts.py

Anvil account 1 is the settlement operator (same key as ``BURSAR_SETTLEMENT_PRIVATE_KEY``).
Anvil account 0 is the household owner; it never sends a chain transaction in the demo, it only
signs the approval digest off-chain.

The two addresses are written to ``/shared/chain.env`` so the API services can source them after
the chain exists (compose starts them once this one-shot exits successfully).
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time

from eth_account import Account
from web3 import Web3

ROOT = pathlib.Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "contracts" / "build" / "contracts.json"
SHARED_ENV = pathlib.Path("/shared/chain.env")

#: 1,000 USDC of demo liquidity (6 decimals).
MINT_AMOUNT = 1_000 * 10**6


def wait_for_node(rpc_url: str, attempts: int = 60) -> Web3:
    last: Exception | None = None
    for _ in range(attempts):
        try:
            w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 2}))
            if w3.is_connected():
                return w3
        except Exception as exc:  # the node is still starting
            last = exc
        time.sleep(1)
    raise SystemExit(f"anvil at {rpc_url} did not answer: {last}")


def load_artifacts() -> dict[str, dict[str, object]]:
    if not ARTIFACTS.exists():
        raise SystemExit(f"missing compiled contracts at {ARTIFACTS}; build the backend image")
    artifacts = json.loads(ARTIFACTS.read_text())
    for name in ("TestUsdc", "PaymentRouter"):
        if name not in artifacts:
            raise SystemExit(f"artifact set has no {name}")
    return artifacts


def _wait(w3: Web3, tx_hash: bytes) -> dict:
    return dict(w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30))


def main() -> int:
    rpc_url = os.environ.get("BURSAR_RPC_URL", "http://anvil:8545")
    settlement_key = os.environ.get("BURSAR_SETTLEMENT_PRIVATE_KEY", "")
    owner = os.environ.get("BURSAR_OWNER_ADDRESS", "")
    if not settlement_key:
        raise SystemExit("BURSAR_SETTLEMENT_PRIVATE_KEY is required")
    if not owner:
        raise SystemExit("BURSAR_OWNER_ADDRESS is required")

    operator = Account.from_key(settlement_key)
    w3 = wait_for_node(rpc_url)
    artifacts = load_artifacts()

    usdc = w3.eth.contract(
        abi=artifacts["TestUsdc"]["abi"], bytecode=artifacts["TestUsdc"]["bin"]
    )
    tx = usdc.constructor().transact({"from": operator.address})
    usdc_receipt = _wait(w3, tx)
    usdc_address = usdc_receipt["contractAddress"]

    router = w3.eth.contract(
        abi=artifacts["PaymentRouter"]["abi"], bytecode=artifacts["PaymentRouter"]["bin"]
    )
    tx = router.constructor(owner, usdc_address).transact({"from": operator.address})
    router_receipt = _wait(w3, tx)
    router_address = router_receipt["contractAddress"]

    token = w3.eth.contract(address=usdc_address, abi=artifacts["TestUsdc"]["abi"])
    _wait(w3, token.functions.mint(operator.address, MINT_AMOUNT).transact({"from": operator.address}))
    _wait(
        w3,
        token.functions.approve(router_address, 2**256 - 1).transact({"from": operator.address}),
    )

    SHARED_ENV.parent.mkdir(parents=True, exist_ok=True)
    SHARED_ENV.write_text(
        f"BURSAR_PAYMENT_ROUTER_ADDRESS={router_address}\n"
        f"BURSAR_USDC_ADDRESS={usdc_address}\n"
    )
    print(f"usdc={usdc_address}")
    print(f"router={router_address}")
    print(f"operator={operator.address} balance={token.functions.balanceOf(operator.address).call()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
