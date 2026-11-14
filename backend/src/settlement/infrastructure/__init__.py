"""Settlement infrastructure — the persistence adapters (Phase B).

Canonical: .pi/architecture/modules/settlement.md#repository-interfaces-owned-by-domain
Reference: docs/contracts/settlement-contract-freeze.md §5

What landed here: SQLAlchemy models, mappers and the three repository adapters, plus the outbox writer.
They satisfy the frozen ports in `domain/repositories.py` and keep the storage guarantees the contract
states — one order per intent (SC-3/SC-4), one spend per nullifier (SC-5), append-only receipts carrying
gas and fee (SC-10).

What did not land, and why it is named rather than stubbed: `Web3RouterAdapter` (needs a funded account and
a deployed `PaymentRouter.sol` on Anvil/Base Sepolia, plus the B-1 re-freeze that lets the hash be
persisted before broadcast). Its contract is the `ChainGateway` port; the runbook records it as gap G-1 so
nobody mistakes a green unit suite for a live chain write. `PaymentRouter.sol` is a Foundry item
(contracts/src) and has no counterpart here yet.

The two adapters that did land live in their own subpackages: `rigorix/` implements `PaymentExecutor`
(`run_command` with the one module-constant command, SC-2) and `authority/` implements `DeterminationGate`
(the live determination read, SC-1). Both are installed by the settlement startup hook.
"""
