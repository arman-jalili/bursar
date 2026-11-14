"""Settlement interfaces — the HTTP surface is frozen in the contract, the router is Phase B.

Canonical: docs/architecture/modules/settlement.md#api-endpoints
Reference: docs/contracts/settlement-contract-freeze.md §2.11

Route handlers are **concrete**, so nothing is frozen as an interface here: `interfaces/http/` gets a
router and Pydantic schemas in Phase B, not a second contract file. What is frozen is the endpoint
shape and the error envelope (`§2.11`), which the console is built against.
"""
