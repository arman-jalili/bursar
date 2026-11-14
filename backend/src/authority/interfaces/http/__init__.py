"""HTTP binding for the Authority context (FastAPI router + wire schemas).

Canonical: .pi/architecture/modules/authority.md#api-endpoints
Reference: docs/contracts/authority-contract-freeze.md §2.9

The module is importable as `from src.authority.interfaces.http import router`; the deployable's
composition root then calls `router.install(app)`, exactly as it does for Mandate.
"""
