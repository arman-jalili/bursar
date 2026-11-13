"""Structured JSON logging + secret redaction + correlation id propagation.

Canonical: .pi/architecture/decisions/ADR-004-api-design.md
Reference: .pi/architecture/decisions/ADR-005-authentication-authorization.md

Why hand-rolled instead of a logging library: the only non-obvious requirement is *redaction*
(ADR-005 forbids secrets in logs) and that requirement is easier to see and test in ~40 lines than
to audit inside a dependency. The `RedactingFilter` is a second line of defence — the first is
`SecretStr` in config, so a secret has no `__str__` that prints it in the first place.

Correlation id: every log line and every error envelope carries one. In this domain it is how you
answer "what happened during that payment?" across five contexts and two processes.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

__all__ = [
    "JsonFormatter",
    "RedactingFilter",
    "configure_logging",
    "correlation_id_var",
    "get_logger",
]

#: Request-scoped correlation id. Set by middleware; read by logs and the error envelope.
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")

#: Substrings (lowercased) that mark a log key as sensitive. Matched against the *key*, so a
#: value that happens to contain "key" in prose is not mangled.
SENSITIVE_KEY_MARKERS: tuple[str, ...] = (
    "hmac",
    "secret",
    "password",
    "private_key",
    "api_key",
    "authorization",
    "token",
    "signature",  # EIP-712 signature bytes are a capability (ADR-005)
)

REDACTED = "«redacted»"


class RedactingFilter(logging.Filter):
    """Replace sensitive values in `record.extra` before they reach a handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in list(vars(record).items()):
            lowered = key.lower()
            if any(marker in lowered for marker in SENSITIVE_KEY_MARKERS):
                setattr(record, key, REDACTED)
            elif isinstance(value, str) and len(value) > 80 and "\n" in value:
                # Multi-line blobs (signed envelopes) are truncated: they are never needed whole
                # in a log and would drown the stream.
                setattr(record, key, value[:80] + "…")
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line — greppable, and shapes match the error envelope."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        correlation_id = correlation_id_var.get()
        if correlation_id:
            payload["correlation_id"] = correlation_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # Everything the caller passed via `extra=` lands as a top-level field.
        for key, value in vars(record).items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        return json.dumps(payload, default=str, separators=(",", ":"))


_RESERVED = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    """Idempotent root configuration. Safe to call from both deployables."""
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RedactingFilter())
    handler.setFormatter(
        JsonFormatter()
        if json_output
        else logging.Formatter("%(levelname)-8s %(name)s %(message)s")
    )
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())
    # uvicorn installs its own handlers; route them through ours so logs stay one format.
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(noisy)
        logger.handlers.clear()
        logger.propagate = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
