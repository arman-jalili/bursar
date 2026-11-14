"""Error envelope — the one shape every failure takes on the wire.

Canonical: docs/architecture/decisions/ADR-004-api-design.md
Reference: docs/architecture/modules/console.md#components

    {"error": {"code", "message", "retryable", "correlation_id", "details"?}}

A refusal is `409` with a domain `code`, and the console translates that code into household
language ("Blocked: the bank details didn't match"). So the envelope is not cosmetic: the code is
the contract between the enforcement layer and the copy the payer reads.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.shared.domain.errors import (
    BursarError,
    ErrorCode,
)
from src.shared.infrastructure.logging import correlation_id_var, get_logger

__all__ = ["install_error_handlers", "request_validation_handler"]

logger = get_logger(__name__)


def _envelope(
    code: ErrorCode,
    message: str,
    correlation_id: str,
    *,
    retryable: bool = False,
    details: dict[str, str] | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "code": str(code),
        "message": message,
        "retryable": retryable,
        "correlation_id": correlation_id,
    }
    if details:
        body["details"] = details
    return {"error": body}


async def request_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Turn pydantic/FastAPI validation errors into the envelope, with field paths."""
    correlation_id = correlation_id_var.get()
    details = {
        ".".join(str(part) for part in error.get("loc", ())) or "body": str(
            error.get("msg", "invalid")
        )
        for error in exc.errors()
    }
    logger.info(
        "request.validation_failed", extra={"path": request.url.path, "fields": sorted(details)}
    )
    return JSONResponse(
        status_code=422,
        content=_envelope(
            ErrorCode.VALIDATION_FAILED,
            "The request could not be processed.",
            correlation_id,
            details=details,
        ),
    )


def install_error_handlers(app: FastAPI) -> None:
    """Register handlers so no endpoint has to build an error body by hand."""

    @app.exception_handler(BursarError)
    async def _bursar_error(_request: Request, exc: BursarError) -> JSONResponse:
        correlation_id = correlation_id_var.get()
        # Refusals are logged at INFO: they are expected outcomes, not incidents.
        level = logger.warning if exc.http_status >= 500 else logger.info
        level(
            "request.refused" if exc.http_status == 409 else "request.error",
            extra={"code": str(exc.code), "status": exc.http_status, "details": exc.details},
        )
        return JSONResponse(status_code=exc.http_status, content=exc.to_envelope(correlation_id))

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return await request_validation_handler(request, exc)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        mapping = {
            401: ErrorCode.UNAUTHENTICATED,
            403: ErrorCode.FORBIDDEN,
            404: ErrorCode.NOT_FOUND,
        }
        code = mapping.get(exc.status_code, ErrorCode.INTERNAL)
        return JSONResponse(
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
            content=_envelope(code, str(exc.detail), correlation_id_var.get()),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        # The message is deliberately not echoed: it could contain a path, a query, a secret.
        logger.exception("request.unhandled", extra={"error": type(exc).__name__})
        return JSONResponse(
            status_code=500,
            content=_envelope(
                ErrorCode.INTERNAL,
                "Something went wrong on our side.",
                correlation_id_var.get(),
                retryable=True,
            ),
        )
