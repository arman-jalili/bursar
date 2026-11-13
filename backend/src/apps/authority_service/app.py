"""Entrypoint: `authority-service` (port 8001).

Canonical: .pi/architecture/modules/authority.md#architecture
Reference: .pi/architecture/decisions/ADR-007-compliance-engine-architecture.md

Run with:  make run-authority         (or: uvicorn src.apps.authority_service.app:app)

Phase 0: boots, answers /healthz and /readyz, exposes the shared kernel only. The Authority
context is registered here in Phase 3 — see `register_routers` in `src/apps/shell.py`.
"""

from __future__ import annotations

import uvicorn

from src.apps.shell import ServiceName, build_app

SERVICE_NAME: ServiceName = "authority-service"
DEFAULT_PORT = 8001

app = build_app(SERVICE_NAME)


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
