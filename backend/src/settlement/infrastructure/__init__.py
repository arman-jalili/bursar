"""Settlement infrastructure — the persistence adapters (Phase B).

Canonical: .pi/architecture/modules/settlement.md#repository-interfaces-owned-by-domain
Reference: docs/contracts/settlement-contract-freeze.md §5

What landed here: SQLAlchemy models, mappers and the three repository adapters, plus the outbox writer.
They satisfy the frozen ports in `domain/repositories.py` and keep the storage guarantees the contract
states — one order per intent (SC-3/SC-4), one spend per nullifier (SC-5), append-only receipts carrying
gas and fee (SC-10).

What did not land, and why it is named rather than stubbed: `RigorixCommandAdapter` (needs the Rigorix
`run_command` runtime) and `Web3RouterAdapter` (needs a funded account and a deployed `PaymentRouter.sol`
on Anvil/Base Sepolia). Their contracts are the `PaymentExecutor` and `ChainGateway` ports; the runbook
records them as the remaining integration gaps so nobody mistakes a green unit suite for a live chain
write. `PaymentRouter.sol` is a Foundry item (contracts/src) and has no counterpart here yet.
"""
