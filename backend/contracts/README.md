# contracts/ — PaymentRouter.sol

**Built.** `contracts/src/PaymentRouter.sol` is Lock 3, the commit-point lock, and
`contracts/src/TestUsdc.sol` is the 6-decimal ERC-20 mock the tests deploy.

Canonical: `docs/architecture/modules/settlement.md#components`
Decision: `docs/architecture/decisions/ADR-007-compliance-engine-architecture.md`
Contract it satisfies: `docs/contracts/settlement-contract-freeze.md` (SC-5, SC-6, SC-9, SC-11)

## What the contract enforces

| Check | Invariant it enforces |
|---|---|
| `nullifier` unspent in `spentNullifiers`, burned before the token call | S-4 / SC-5 / SC-6 / scenario 6 — an invoice settles at most once, even with the app bypassed |
| `ecrecover` of the EIP-712 signature equals the immutable `owner` | A-15 — the second lock stays shut, and a stolen operator key cannot pay |
| the signed struct carries `orderId`, `nullifier`, `payer`, `payee`, `amount` | S-2 / SC-9 — no late destination or amount substitution, and no cross-operator replay |
| domain separator = name + version + `chainId` + `verifyingContract` | SC-11 — a signature for one chain/router cannot be replayed on another |
| `Anchored(orderId indexed, nullifier indexed, txRef)` on `pay` and `anchor` | the app binds a receipt to an order; anchoring is never mistaken for a settlement (ADR-006) |
| `anchor(bytes32)` | E-3 / scenario 7 — independent integrity and time, spending no nullifier |

Named errors (`NullifierSpent`, `OwnerSignatureInvalid`, `OwnerSignatureRequired`, `TransferFailed`,
`AmountNotPositive`, `ZeroAddress`) are the refusal vocabulary on-chain: the Python adapter decodes the
selector, so a refusal is a documented 409 rather than a reworded string.

## Toolchain — read this before adding a Foundry-only step

`foundry.toml` pins `solc_version = "0.8.24"`, `evm_version = "paris"`, optimizer 200 runs.

`forge`, `anvil` and `cast` are **not installed everywhere this repository is worked on**, so the tests
do not depend on them:

```bash
# contract tests — no foundry, no anvil, no network (first run downloads solc 0.8.24 once)
cd backend && .venv/bin/python -m pytest tests/unit/settlement/chain -q

# on a machine with foundry, the same contracts build and deploy
make anvil
make contracts-build
make contracts-test
```

`contracts/test/PaymentRouter.t.sol` does not exist on purpose: a Foundry test that cannot run here is a
test nobody runs. The equivalent rules live in
`backend/tests/unit/settlement/chain/test_payment_router_contract.py`, which compiles these sources with
`py-solc-x` and executes them on `eth-tester`'s py-evm backend. That suite also asserts the adapter's
embedded ABI (`backend/src/settlement/infrastructure/chain/abi.py`) equals the compiler's ABI, so the
Solidity and the Python cannot drift silently (ADR-007).

## Deployment

Deployment addresses land in `.env` (`BURSAR_PAYMENT_ROUTER_ADDRESS`, `BURSAR_USDC_ADDRESS`) and are read
through `ChainNetwork` — never hardcoded in Python. Anvil and Base Sepolia must never share a chain id,
router or USDC address (SC-11); `Web3ChainGateway` refuses to build for a chain id the provider is not on.

The contract is deployed but **nothing has been broadcast on Anvil or Base Sepolia yet** — that is the
remaining operational gap recorded in the settlement contract.
