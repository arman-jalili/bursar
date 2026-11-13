"""Billing interfaces — the driving adapters (Phase B).

Canonical: .pi/architecture/modules/billing.md#api-endpoints
Reference: docs/contracts/billing-contract-freeze.md §5

Empty on purpose in Phase A. Routers and Pydantic request/response schemas are **concrete**; they do
not get interface files of their own (a router is already the boundary, and a contract for it would
be a second, drifting description).

The frozen part is the endpoint shape, documented in the module doc and in the freeze doc:
`POST/GET /v1/invoices`, `POST/GET /v1/attempts`, with error responses in the shared ADR-004
envelope. Registration in the app shell is part of the runtime-integration item.
"""
