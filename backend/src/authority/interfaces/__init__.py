"""Authority interfaces — the driving adapters (Phase B).

Canonical: .pi/architecture/modules/authority.md#api-endpoints
Reference: docs/contracts/authority-contract-freeze.md §2.9

Empty on purpose in Phase A. Routers and Pydantic request/response schemas are **concrete**; they do
not get interface files of their own. A router is already the boundary, and a contract for it would
be a second, drifting description of the same endpoints.

The frozen part is the endpoint shape, documented in the module doc and in §2.9 of the freeze doc:
`POST /v1/precondition/check` (the fail-closed Lock-2 entry), `POST /v1/attempts/{id}/evaluate`, the
intent/determination/ledger reads, the approval inbox and signature submission, and the settlement
outcome callback. Error responses use the shared ADR-004 envelope. Registration in the app shell is
part of the runtime-integration item.
"""

__all__: list[str] = []
