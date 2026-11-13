"""Settlement infrastructure — adapters arrive in Phase B; the package exists, the code does not.

Canonical: .pi/architecture/modules/settlement.md#ports-infrastructure-adapters
Reference: docs/contracts/settlement-contract-freeze.md §5

Frozen here: the three **ports** (`PaymentExecutor`, `ChainGateway`, `DeterminationGate`) and the
repository interfaces in `domain/`. Deliberately absent: `RigorixCommandAdapter`,
`Web3RouterAdapter`, `AuthorityHttpAdapter`, SQLAlchemy models and the migration.

A contract freeze that also ships adapters is not a freeze — it hides which guarantees are still
missing. The on-chain second lock (`PaymentRouter.sol`) and the Anvil deployment are Phase B items
too; the contract they must satisfy is `ChainGateway` plus SC-5/SC-6/SC-11.
"""
