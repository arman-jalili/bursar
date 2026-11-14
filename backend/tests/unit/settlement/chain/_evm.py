"""Compile `contracts/src` with solc 0.8.24 and deploy it to an in-process EVM.

Canonical: `docs/contracts/settlement-contract-freeze.md` §1 (SC-5, SC-6, SC-9, SC-10)
Reference: `docs/architecture/modules/settlement.md#components`

`forge`/`anvil` are not installed here, so the Solidity is compiled with `py-solc-x` and executed on
`eth-tester`'s py-evm backend. That is the real compiler and a real EVM: the tests below assert the
contract's behaviour (storage, events, named errors, EIP-712 recovery), not a mock of it.

Two properties make this a test of the contract rather than of a fixture:

* the bytecode comes from `contracts/src/*.sol` at test time, so a change to the Solidity is exercised
  immediately — there is no checked-in artifact that can go stale;
* the deployer/operator keys are the tester backend's own funded accounts, so transactions are signed
  locally exactly as the gateway signs them (`eth_account`, EIP-1559, raw broadcast).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import solcx
from eth_account import Account
from eth_utils import keccak, to_checksum_address
from hexbytes import HexBytes

# ── compile ─────────────────────────────────────────────────────────────────

#: Pinned to `foundry.toml`'s `solc_version` and `evm_version`. A different compiler or EVM target would
#: test a different contract than the one base-sepolia/anvil will run.
SOLC_VERSION = "0.8.24"
EVM_VERSION = "paris"
OPTIMIZER_RUNS = 200

CONTRACTS_DIR = Path(__file__).resolve().parents[4] / "contracts" / "src"


@dataclass(frozen=True)
class CompiledContracts:
    """ABI + creation bytecode per contract name, from one solc invocation."""

    abi: dict[str, list[dict[str, Any]]]
    bytecode: dict[str, str]
    version: str


@lru_cache(maxsize=1)
def compiled_contracts() -> CompiledContracts:
    """Compile every `.sol` under `contracts/src` once per session.

    `solcx.install_solc` is idempotent: it returns the cached compiler when the pinned version is
    already present, so a machine without 0.8.24 downloads it once and later runs need no network.
    """
    if not any(str(version) == SOLC_VERSION for version in solcx.get_installed_solc_versions()):
        solcx.install_solc(SOLC_VERSION)

    sources = {
        path.name: {"content": path.read_text(encoding="utf-8")}
        for path in sorted(CONTRACTS_DIR.glob("*.sol"))
    }
    if "PaymentRouter.sol" not in sources:
        raise AssertionError(f"PaymentRouter.sol not found under {CONTRACTS_DIR}")

    output = solcx.compile_standard(
        {
            "language": "Solidity",
            "sources": sources,
            "settings": {
                "optimizer": {"enabled": True, "runs": OPTIMIZER_RUNS},
                "evmVersion": EVM_VERSION,
                "outputSelection": {"*": {"*": ["abi", "evm.bytecode.object"]}},
            },
        },
        solc_version=SOLC_VERSION,
    )

    abi: dict[str, list[dict[str, Any]]] = {}
    bytecode: dict[str, str] = {}
    for contracts in output["contracts"].values():
        for name, artifact in contracts.items():
            abi[name] = artifact["abi"]
            bytecode[name] = artifact["evm"]["bytecode"]["object"]
    return CompiledContracts(abi=abi, bytecode=bytecode, version=SOLC_VERSION)


# ── a deployed local chain ──────────────────────────────────────────────────


def decode_revert_name(exc: BaseException) -> str:
    """The contract's named error from a provider exception, or `''` when it is not a named revert.

    Kept local to the suite on purpose: this is the *assertion* helper ("the revert names
    `NullifierSpent`"), not the adapter's mapping. It decodes the same bytes the adapter decodes, so a
    test that passes here and fails there would mean the adapter's mapping is wrong.
    """
    from src.settlement.infrastructure.chain.abi import ROUTER_ERROR_SELECTORS
    from src.settlement.infrastructure.chain.web3_gateway import revert_payload

    payload = revert_payload(exc)
    if len(payload) < 4:
        return ""
    return ROUTER_ERROR_SELECTORS.get("0x" + payload[:4].hex(), "")


@dataclass
class LocalChain:
    """A py-evm chain with `PaymentRouter` + `TestUsdc` deployed, and funded signers."""

    w3: Any
    tester: Any
    contracts: CompiledContracts
    owner_key: bytes
    operator_key: bytes
    owner: str
    operator: str
    usdc: Any
    router: Any
    payee: str

    # ── transaction helpers ─────────────────────────────────────────────────

    def send(self, function_call: Any, key: bytes | None = None, *, gas: int = 500_000) -> HexBytes:
        """Sign with `key` (default: the operator) and broadcast. No node-side signing anywhere."""
        signer = Account.from_key(key or self.operator_key)
        transaction = function_call.build_transaction(
            {
                "from": signer.address,
                "value": 0,
                "gas": gas,
                "chainId": self.w3.eth.chain_id,
                "nonce": self.w3.eth.get_transaction_count(signer.address),
                "maxFeePerGas": 2_000_000_000,
                "maxPriorityFeePerGas": 1_000_000_000,
            }
        )
        signed = Account.sign_transaction(transaction, key or self.operator_key)
        return HexBytes(self.w3.eth.send_raw_transaction(signed.raw_transaction))

    def call(self, function_call: Any, from_: str | None = None) -> Any:
        """Execute without mining — a revert raises here, which is what the named-error tests want."""
        return function_call.call({"from": from_ or self.operator})

    def wait(self, tx_hash: HexBytes) -> Any:
        return self.w3.eth.wait_for_transaction_receipt(tx_hash)

    def fund_operator(self, amount: int = 100_000_000) -> None:
        """Mint `amount` micro-USDC (100 USDC) to the operator and approve the router."""
        self.usdc.functions.mint(self.operator, amount).transact({"from": self.operator})
        self.usdc.functions.approve(self.router.address, amount).transact({"from": self.operator})

    # ── order / signature helpers ───────────────────────────────────────────

    @staticmethod
    def order_ref(order_id: str) -> bytes:
        """`bytes32` of the off-chain order id — the same mapping the gateway uses."""
        return keccak(text=str(order_id))

    @staticmethod
    def nullifier_word(marker: str) -> bytes:
        return bytes.fromhex(marker[2:] if marker.startswith("0x") else marker)

    def payment_typed_data(
        self,
        *,
        order_ref: bytes,
        nullifier: bytes,
        payee: str,
        amount: int,
        payer: str | None = None,
    ) -> dict[str, Any]:
        """The EIP-712 document the owner signs — field order and types mirror the Solidity struct."""
        return {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "Payment": [
                    {"name": "orderId", "type": "bytes32"},
                    {"name": "nullifier", "type": "bytes32"},
                    {"name": "payer", "type": "address"},
                    {"name": "payee", "type": "address"},
                    {"name": "amount", "type": "uint256"},
                ],
            },
            "primaryType": "Payment",
            "domain": {
                "name": "Bursar PaymentRouter",
                "version": "1",
                "chainId": self.w3.eth.chain_id,
                "verifyingContract": self.router.address,
            },
            "message": {
                "orderId": order_ref,
                "nullifier": nullifier,
                "payer": payer or self.operator,
                "payee": payee,
                "amount": amount,
            },
        }

    def sign_payment(self, key: bytes, **fields: Any) -> bytes:
        """Owner (or attacker) signature over the payment struct, 65 bytes `r || s || v`."""
        signed = Account.sign_typed_data(key, full_message=self.payment_typed_data(**fields))
        return bytes(signed.signature)


def deploy_local_chain() -> LocalChain:
    """A fresh py-evm chain per test: no snapshot juggling, no order-dependent state."""
    from eth_tester import EthereumTester, PyEVMBackend
    from eth_tester.backends.pyevm.main import get_default_account_keys
    from web3 import EthereumTesterProvider, Web3

    contracts = compiled_contracts()
    keys = get_default_account_keys()
    owner_key = bytes(keys[0].to_bytes())
    operator_key = bytes(keys[1].to_bytes())
    owner = to_checksum_address(Account.from_key(owner_key).address)
    operator = to_checksum_address(Account.from_key(operator_key).address)

    tester = EthereumTester(backend=PyEVMBackend())
    w3 = Web3(EthereumTesterProvider(tester))

    def deploy(name: str, *arguments: Any) -> Any:
        factory = w3.eth.contract(abi=contracts.abi[name], bytecode=contracts.bytecode[name])
        receipt = w3.eth.wait_for_transaction_receipt(
            factory.constructor(*arguments).transact({"from": w3.eth.accounts[0]})
        )
        return w3.eth.contract(address=receipt.contractAddress, abi=contracts.abi[name])

    usdc = deploy("TestUsdc")
    router = deploy("PaymentRouter", owner, usdc.address)

    chain = LocalChain(
        w3=w3,
        tester=tester,
        contracts=contracts,
        owner_key=owner_key,
        operator_key=operator_key,
        owner=owner,
        operator=operator,
        usdc=usdc,
        router=router,
        payee=to_checksum_address("0x" + "11" * 20),
    )
    chain.fund_operator()
    return chain
