"""Application shell — the composition root both deployables share.

Canonical: .pi/architecture/decisions/ADR-001-architecture-pattern.md
Reference: .pi/architecture/implementation-roadmap.md#phase-0-project-bootstrap-hours-01

A composition root is the *only* place allowed to know about every layer: it builds the engine,
installs middleware and error handlers, and registers routers. Nothing else in the codebase may
construct infrastructure (that rule is what keeps the domain testable without a server).

Phase 0 note — this shell deliberately contains **no context routers**. `register_routers()` is the
seam; each build phase adds its own `include_router` call there and nowhere else. If we pre-listed
routers that do not exist, `/readyz` would claim a system that is not there — the exact failure
mode `check_composition_root.sh` exists to catch.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.shared.infrastructure.config import Settings, get_settings
from src.shared.infrastructure.db import build_engine, build_session_factory
from src.shared.infrastructure.logging import configure_logging, get_logger
from src.shared.infrastructure.middleware import CorrelationIdMiddleware, MetricsMiddleware
from src.shared.infrastructure.migrations import upgrade_to_head_async
from src.shared.interfaces.errors import install_error_handlers
from src.shared.interfaces.health import build_health_router, metrics_router

__all__ = ["ServiceName", "build_app", "install_context"]

logger = get_logger(__name__)

ServiceName = Literal["authority-service", "console-api"]

#: Contexts each deployable will host once built (roadmap Phases 1-6). Reported by `/readyz` so a
#: skeleton states its gaps rather than implying completeness.
CONTEXT_PLAN: dict[ServiceName, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "authority-service": ((), ("Authority",)),
    "console-api": (("Mandate",), ("Billing", "Settlement", "Evidence", "Console")),
}


def install_context(app: FastAPI, context: object) -> None:
    """Register one context's router and its startup hook.

    Each deployable's `app.py` calls this once per hosted context, so the file that *is* the
    composition root also reads as the list of what it hosts. The startup hook runs inside the
    lifespan, after the engine exists, because application services take a session factory — a
    composition root that pretends otherwise is how a factory ends up being built twice.
    """
    installer = getattr(context, "install", None)
    if installer is None:  # pragma: no cover - guarded by the type of context we pass
        raise TypeError(f"{context!r} is not an installable context module")
    installer(app)


def build_app(service: ServiceName, settings: Settings | None = None) -> FastAPI:
    """Build a deployable's FastAPI app. Called by `app.py` and by tests."""
    cfg = settings or get_settings()
    configure_logging(cfg.log_level, json_output=cfg.log_json)

    database_url = cfg.database_url_for(
        "authority" if service == "authority-service" else "console"
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = build_engine(database_url, busy_timeout_ms=cfg.sqlite_busy_timeout_ms)
        app.state.session_factory = build_session_factory(app.state.engine)
        # One schema definition (Alembic), applied at boot so a clean checkout just works.
        await upgrade_to_head_async(database_url)
        for hook in app.state.startup_hooks:
            hook(app)
        logger.info(
            "service.started",
            extra={"service": service, "phase": 0, "env": cfg.env, "chain": str(cfg.chain)},
        )
        try:
            yield
        finally:
            await app.state.engine.dispose()
            logger.info("service.stopped", extra={"service": service})

    app = FastAPI(
        title=f"Bursar — {service}",
        version="0.1.0",
        description=(
            "Delegated household bill-paying. The agent proposes; the code disposes.\n\n"
            "Phase 0 skeleton: health and shared kernel only. Contexts arrive per "
            "`.pi/architecture/implementation-roadmap.md`."
        ),
        lifespan=lifespan,
        openapi_url="/openapi.json",
        docs_url="/docs",
    )

    # Middleware order: correlation id outermost so every log line inside has an id.
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(MetricsMiddleware)
    if service == "console-api":
        # Only the console is browser-facing (ADR-001). The authority service must not be
        # reachable from a page — it is the enforcement lock, not a UI backend.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-Id"],
        )

    install_error_handlers(app)
    app.include_router(metrics_router)
    #: Filled by `install_context` before the app starts; run once the engine exists.
    app.state.startup_hooks = []

    wired, pending = CONTEXT_PLAN[service]

    async def _engine_provider() -> object:
        return app.state.engine

    app.include_router(
        build_health_router(
            service_name=service,
            settings=cfg,
            engine_provider=_engine_provider,  # type: ignore[arg-type]
            wired_contexts=wired,
            pending_contexts=pending,
        )
    )

    return app
