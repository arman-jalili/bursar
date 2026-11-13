"""Settlement domain — framework-free, chain-free, persistence-ignorant.

Canonical: .pi/architecture/modules/settlement.md#components
Reference: docs/contracts/settlement-contract-freeze.md

AC-12 (SC-12) is enforced here structurally: nothing in this package imports `web3`, `httpx` or
`fastapi`. The chain is a *port* (`ChainGateway`), so the aggregate can prove its invariants in a unit
test without an RPC endpoint — and the on-chain lock can be reasoned about without the domain knowing
which library talks to it.

`PayeeAddress` is **not** redefined here. Settlement is conformist to Mandate (context map): the address
carried on the intent is `src.mandate.domain.values.PayeeAddress`, validated by the context that owns
it. A second address type in Settlement would let one side accept a destination the other rejects.

Every function body raises `NotImplementedError("SC-n — see module doc")` until Phase B. The suffix is
the invariant the body must satisfy, not a decoration: it is what the failing tests point at.
"""
