"""Health endpoints — `/healthz` (liveness) and `/readyz` (readiness).

Canonical: .pi/architecture/decisions/ADR-007-compliance-engine-architecture.md
Reference: .pi/architecture/implementation-roadmap.md#phase-0-project-bootstrap-hours-01

The distinction is load-bearing in this domain:

* `/healthz` answers "is the process alive?" It must not touch the database or the chain — a
  liveness probe that depends on an external system will restart a healthy process when the
  network blips.
* `/readyz` answers "should traffic be sent here?" It checks the database, and reports what is
  *not yet built* (contexts, contract) without failing. A Phase-0 skeleton must be honestly
  ready-for-nothing rather than pretending to be a finished service.

For `authority-service`, readiness also matters for the enforcement story: ADR-007 says the
precondition check **fails closed**. So `/readyz` reporting `database: false` means Rigorix must
refuse dispatch — the health surface is part of the safety argument, not just ops.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncEngine

from src.shared.infrastructure.config import Settings
from src.shared.infrastructure.db import ping

__all__ = ["SERVICE_STARTED_AT", "build_health_router"]

SERVICE_STARTED_AT = datetime.now(UTC)


def build_health_router(
    *,
    service_name: str,
    settings: Settings,
    engine_provider: Callable[[], Awaitable[AsyncEngine]] | None = None,
    wired_contexts: tuple[str, ...] = (),
    pending_contexts: tuple[str, ...] = (),
) -> APIRouter:
    """Build the health router for one deployable."""
    router = APIRouter(tags=["health"])

    @router.get("/healthz", summary="Liveness — process is up")
    async def healthz() -> dict[str, object]:
        return {
            "status": "ok",
            "service": service_name,
            "uptime_seconds": int((datetime.now(UTC) - SERVICE_STARTED_AT).total_seconds()),
        }

    @router.get("/readyz", summary="Readiness — dependencies and build state")
    async def readyz(request: Request) -> JSONResponse:
        engine: AsyncEngine | None = None
        if engine_provider is not None:
            engine = await engine_provider()
        else:  # pragma: no cover - both deployables pass a provider
            engine = getattr(request.app.state, "engine", None)

        database_ok = await ping(engine) if engine is not None else False

        body: dict[str, object] = {
            "status": "ready" if database_ok else "not_ready",
            "service": service_name,
            "checks": {
                "config": "ok",
                "database": "ok" if database_ok else "unavailable",
            },
            "build": {
                "phase": 0,
                "wired_contexts": list(wired_contexts),
                # Honest: a Phase-0 skeleton has no bounded contexts yet. Listed so /readyz
                # documents the gap instead of implying a complete system.
                "pending_contexts": list(pending_contexts),
            },
            "config": settings.safe_dump(),
        }
        return JSONResponse(status_code=200 if database_ok else 503, content=body)

    return router
