"""`GET /v1/engine/status` — which enforcement engine is actually answering, right now.

Why this endpoint exists
------------------------
A demo that says "Rigorix is enforcing this" over a picture of a logo is unfalsifiable, and the
reviewer is right to distrust it. This endpoint replaces the logo with quotable data: the engine's
own `rigorix.system.version` answer, the round-trip that produced it, and the anchor head it
reports — fetched through *this* service so the browser can display it, and copyable so a reviewer
can reproduce it from a terminal.

Two deliberate choices
----------------------
* **No cache.** `Cache-Control: no-store`. A status surface that can be served from a cache is a
  status surface that can lie about a dead dependency; the whole point is that the number is live.
* **200 with `reachable: false`, not 503.** The endpoint's own liveness is "the API answered"; the
  engine's liveness is a *field*. Returning 503 would make a page's health check and the engine's
  health indistinguishable in a log, and the UI needs the body to render the red strip rather than
  a fetch failure. Monitoring alerts on the field.

What is deliberately NOT claimed here
-------------------------------------
`reachable: true` proves nothing about *which* engine it is. That is why the version fields are
passed through verbatim, including `engine_version` and `api_version`: a browser pinned to the
catalog can check `api_version` itself, and a mismatch is visible rather than asserted.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.shared.infrastructure.config import Settings

__all__ = ["build_engine_router", "read_engine_version"]

logger = logging.getLogger(__name__)

#: Fields of `rigorix.system.version` copied through unchanged. Anything an operator would quote in
#: a bug report belongs here; everything else is noise the UI would have to guess about.
_VERSION_FIELDS = (
    "name",
    "engine_version",
    "api_version",
    "anchor",
    "history_integrity",
    "capabilities",
    "schemas",
)


def read_engine_version(base_url: str, timeout_seconds: float) -> dict[str, Any]:
    """Ask the engine for its version. Blocking, on purpose — the handler moves it to a thread.

    Raises whatever the transport raises: the caller turns that into `reachable: false` with the
    message, because "the engine is unreachable" is a reportable state, not a crash.
    """
    # Imported here so a boot that never asks for status does not pay for the client, and ignored
    # for typing because the published package ships no `py.typed` marker — the boundary is a
    # third-party transport, so its types are unknown to us by construction.
    from rigorix_verifier.client import Client, HTTPTransport  # type: ignore[import-untyped]

    client = Client(HTTPTransport(f"{base_url.rstrip('/')}/rpc", timeout=timeout_seconds))
    return client.version()


def build_engine_router(settings: Settings) -> APIRouter:
    """The engine-status route, bound to this deployment's settings."""
    router = APIRouter()

    @router.get("/v1/engine/status", tags=["ops"])
    async def engine_status(request: Request) -> JSONResponse:
        """Proxy the engine's version, with the latency it took and its reachability stated."""
        started = time.perf_counter()
        base_url = str(getattr(request.app.state, "rigorix_base_url", settings.rigorix_base_url))
        timeout = float(
            getattr(request.app.state, "rigorix_timeout", settings.rigorix_rpc_timeout_seconds)
        )
        try:
            version = await asyncio.to_thread(read_engine_version, base_url, timeout)
        except Exception as exc:
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            logger.warning("engine.status.unreachable", extra={"base_url": base_url})
            body: dict[str, Any] = {
                "reachable": False,
                "base_url": base_url,
                "latency_ms": elapsed,
                # The class name and message only: an exception's repr can carry a URL with
                # credentials, and this response goes to a browser.
                "error": f"{type(exc).__name__}: {exc}",
                "endpoint": f"{base_url.rstrip('/')}/rpc",
            }
            return JSONResponse(body, headers={"Cache-Control": "no-store"})

        elapsed = round((time.perf_counter() - started) * 1000, 1)
        body = {
            "reachable": True,
            "base_url": base_url,
            "latency_ms": elapsed,
            "endpoint": f"{base_url.rstrip('/')}/rpc",
            **{key: version[key] for key in _VERSION_FIELDS if key in version},
            # The whole answer, so the UI can show "raw" without a second request and a reviewer
            # can diff what the page displayed against what the engine said.
            "raw": version,
        }
        return JSONResponse(body, headers={"Cache-Control": "no-store"})

    return router