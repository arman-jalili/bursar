# contracts/ — PaymentRouter.sol

**Phase 0 scaffold.** Empty by design: the contract is written in Phase 4 of
`.pi/architecture/implementation-roadmap.md`.

Canonical: `.pi/architecture/modules/settlement.md#components`
Decision: `.pi/architecture/decisions/ADR-007-compliance-engine-architecture.md`

## What lives here in Phase 4

`contracts/src/PaymentRouter.sol` — **Lock 3**, the commit-point lock. It re-checks, on-chain,
what the off-chain layers already decided:

| Check | Invariant it enforces |
|---|---|
| `nullifier = keccak(invoiceHash)` unspent | S-4 / scenario 6 — an invoice settles at most once |
| EIP-712 signature recovers to `owner` | A-15 / scenario 5 — the signature is bound to those exact bytes |
| `payeeAddress` equals the signed address | S-2 — no late destination substitution |
| `amountUsdc` equals the signed amount | S-3 — no late amount substitution |
| anchor store `anchor(bytes32 hash)` | E-3 / scenario 7 — independent integrity and time |

## Why it is empty right now

Writing the contract before the EIP-712 struct is fixed would guarantee a mismatch between the
Python verifier and the Solidity verifier — the highest-severity defect class in this project
(ADR-007). The struct spec is defined once and consumed by both; that happens in Phase 3/4.

## Commands

```bash
make anvil          # local chain on :8545
make contracts-build
make contracts-test
```

Deployment addresses land in `.env` (`BURSAR_PAYMENT_ROUTER_ADDRESS`, `BURSAR_USDC_ADDRESS`) and are
read through `ChainNetwork` — never hardcoded in Python.
