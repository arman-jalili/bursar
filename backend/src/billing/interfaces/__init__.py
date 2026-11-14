"""Billing interfaces — the driving adapters.

Canonical: docs/architecture/modules/billing.md#api-endpoints
Reference: docs/contracts/billing-contract-freeze.md §2.10

The router is **concrete** (no interface file for controllers): there is exactly one transport for this
context, so an abstraction over it would be speculative. It is registered by
`src/apps/console_api/app.py`, the only place allowed to know about it.

Endpoint contract (`http/router.py`): `POST/GET /v1/invoices`, `POST/GET /v1/attempts`, all failures in
the shared ADR-004 envelope. A proposal carrying a forbidden field is rejected with
`422 PROPOSAL_REJECTED` before an attempt exists (B-5).
"""
