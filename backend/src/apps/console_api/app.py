"""Entrypoint: `console-api` (port 8000).

Canonical: .pi/architecture/modules/console.md#architecture
Reference: .pi/architecture/implementation-roadmap.md#phase-6-console-hours-1620

Run with:  make run-console           (or: uvicorn src.apps.console_api.app:app)

Phase 0: boots, answers /healthz and /readyz, serves CORS for the Vite dev origin. Contexts are
registered here in Phases 1, 2, 4, 5, 6 — see `register_routers` in `src/apps/shell.py`.
"""

from __future__ import annotations

import uvicorn

from src.apps.shell import ServiceName, build_app

SERVICE_NAME: ServiceName = "console-api"
DEFAULT_PORT = 8000

app = build_app(SERVICE_NAME)


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
