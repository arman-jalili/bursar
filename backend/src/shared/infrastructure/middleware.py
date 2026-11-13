"""Correlation-id middleware — one id per request, threaded through logs and errors.

Canonical: .pi/architecture/decisions/ADR-004-api-design.md
Reference: .pi/architecture/decisions/ADR-003-cross-context-communication.md

The id is accepted from `X-Request-Id` when the caller supplies one (so a proposal submitted by the
agent can be traced through Authority), and generated otherwise. It is echoed on the response and
embedded in every error envelope, which is what makes "show me what happened to that payment"
answerable without a log grep by timestamp.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.shared.infrastructure.logging import correlation_id_var, get_logger

__all__ = ["CORRELATION_HEADER", "CorrelationIdMiddleware"]

CORRELATION_HEADER = "X-Request-Id"
_MAX_ID_LENGTH = 128

logger = get_logger(__name__)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Bind a correlation id to the request scope for the lifetime of the request."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get(CORRELATION_HEADER, "").strip()
        # Validate rather than trust: an unbounded header would end up in every log line.
        correlation_id = incoming[:_MAX_ID_LENGTH] if incoming else uuid.uuid4().hex
        token = correlation_id_var.set(correlation_id)
        try:
            response = await call_next(request)
            response.headers[CORRELATION_HEADER] = correlation_id
            return response
        finally:
            correlation_id_var.reset(token)
