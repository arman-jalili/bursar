"""Entrypoint: `authority-service` (port 8001).

Canonical: .pi/architecture/modules/authority.md#architecture
Reference: .pi/architecture/decisions/ADR-007-compliance-engine-architecture.md

Run with:  make run-authority         (or: uvicorn src.apps.authority_service.app:app)

The **composition root for this deployable** lives here, mirroring `console_api/app.py`:
`HOSTED_CONTEXTS` is the list of bounded contexts this process serves, and it is the only place that
knows them. Authority is the reason this service exists — the enforcement lock is not a UI backend and
must not be reachable from a browser page (no CORS middleware in the shell for this service).
"""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI

from src.apps.shell import ServiceName, build_app, install_context
from src.authority.interfaces.http import router as authority

SERVICE_NAME: ServiceName = "authority-service"
DEFAULT_PORT = 8001

#: Bounded contexts hosted by this deployable. Authority is the whole enforcement surface: the
#: precondition check, evaluation, the intent/ledger reads, the approval inbox and settlement outcomes.
#: The router's `build_services` composes the application layer for it: the five catalog services in
#: `src/authority/application/services_impl.py`, the fail-closed `PreconditionCheck` façade, and the
#: read side in `src/authority/application/queries.py` (`AuthorityQueries` — the GET endpoints).
HOSTED_CONTEXTS = (
    authority,  # Authority (Phase 3) — A-1 … A-15, fail-closed Lock 2
)


def build(settings: object | None = None) -> FastAPI:
    """Build the deployable with its contexts installed (tests and the entrypoint share this)."""
    application = build_app(SERVICE_NAME, settings=settings)  # type: ignore[arg-type]
    for context in HOSTED_CONTEXTS:
        install_context(application, context)
    return application


app = build()


def main() -> None:
    """Console-script entrypoint (`authority-service` in pyproject)."""
    uvicorn.run(
        "src.apps.authority_service.app:app",
        host="127.0.0.1",
        port=DEFAULT_PORT,
        reload=False,
        log_config=None,  # our JSON logging owns the format
    )


if __name__ == "__main__":
    main()
