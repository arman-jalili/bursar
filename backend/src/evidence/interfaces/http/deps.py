"""ADR-005 scope checks for the Evidence transport.

Canonical: docs/architecture/decisions/ADR-005-authentication-authorization.md
Reference: docs/architecture/modules/evidence.md#api-endpoints

Evidence is read-mostly: the owner/auditor may read envelopes and anchors (`evidence:read`), while
the console renders the verified/tampered toggle with `console:read`. The map is local to Evidence so
the module can be deployed without importing another context's transport layer.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from collections.abc import Set as AbstractSet

from fastapi import Header, status

from src.shared.domain.errors import ForbiddenError

__all__ = ["require_any_scope", "require_scope"]

_DEMO_TOKENS: dict[str, frozenset[str]] = {
    "demo-owner-token": frozenset({"evidence:read", "mandate:read", "authority:read"}),
    "demo-agent-token": frozenset({"billing:propose", "billing:read", "authority:evaluate"}),
    "demo-payer-token": frozenset({"console:read", "billing:read"}),
}


def _scopes_for(token: str) -> frozenset[str]:
    return _DEMO_TOKENS.get(token, frozenset())


def _bearer(authorization: str | None) -> frozenset[str]:
    if not authorization or not authorization.lower().startswith("bearer "):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _scopes_for(authorization.split(" ", 1)[1].strip())


def require_scope(scope: str) -> Callable[..., Awaitable[frozenset[str]]]:
    """Build a dependency that enforces one scope on the bearer token."""

    async def _dependency(authorization: str | None = Header(default=None)) -> frozenset[str]:
        scopes = _bearer(authorization)
        if scope not in scopes:
            raise ForbiddenError(
                f"this credential lacks the {scope} scope",
                required_scope=scope,
                granted=",".join(sorted(scopes)) or "none",
            )
        return scopes

    return _dependency


def require_any_scope(scopes: AbstractSet[str]) -> Callable[..., Awaitable[frozenset[str]]]:
    """Build a dependency that accepts any one of the listed scopes."""

    required = frozenset(scopes)

    async def _dependency(authorization: str | None = Header(default=None)) -> frozenset[str]:
        granted = _bearer(authorization)
        if not (required & granted):
            raise ForbiddenError(
                "this credential lacks a scope this endpoint requires",
                required_scope=",".join(sorted(required)),
                granted=",".join(sorted(granted)) or "none",
            )
        return granted

    return _dependency
