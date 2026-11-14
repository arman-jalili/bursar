"""Entrypoint: `console-api` (port 8000).

Canonical: .pi/architecture/modules/console.md#architecture
Reference: .pi/architecture/implementation-roadmap.md#phase-6-console-hours-1620

Run with:  make run-console           (or: uvicorn src.apps.console_api.app:app)

The **composition root** lives in this file: `HOSTED_CONTEXTS` is the list of bounded contexts this
deployable serves, and it is the only place that knows all of them. A context that is implemented but
not listed here does not exist at runtime — exactly what `check_composition_root.sh` exists to catch.
"""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI

from src.apps.shell import ServiceName, build_app, install_context
from src.billing.interfaces.http import router as billing
from src.evidence.interfaces.http import router as evidence
from src.mandate.interfaces.http import router as mandate
from src.settlement.interfaces.http import router as settlement

SERVICE_NAME: ServiceName = "console-api"
DEFAULT_PORT = 8000

#: Bounded contexts hosted by this deployable (ADR-001: one process, one database file).
#: Each build phase adds its module here and nothing else changes at the edge.
HOSTED_CONTEXTS = (
    mandate,  # Mandate (Phase 1) — payees, constitution lineage, eligibility read-through
    billing,  # Billing (Phase 2) — invoices, payment attempts, duplicate + one-active guards
    settlement,  # Settlement (Phase 4) — orders, receipts, cost, nullifier status (read side)
    evidence,  # Evidence (Phase 5) — append-only envelopes, anchors, verify/tamper surface
    # Console (Phase 6) follows.
)


def build(settings: object | None = None) -> FastAPI:
    """Build the deployable with its contexts installed (tests and the entrypoint share this)."""
    application = build_app(SERVICE_NAME, settings=settings)  # type: ignore[arg-type]
    for context in HOSTED_CONTEXTS:
        install_context(application, context)
    return application


app = build()


def main() -> None:
    """Console-script entrypoint (`console-api` in pyproject)."""
    uvicorn.run(
        "src.apps.console_api.app:app",
        host="127.0.0.1",
        port=DEFAULT_PORT,
        reload=False,
        log_config=None,
    )


if __name__ == "__main__":
    main()
