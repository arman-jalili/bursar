"""ADR-005 scope checks for the Settlement transport.

Canonical: .pi/architecture/decisions/ADR-005-authentication-authorization.md
Reference: .pi/architecture/modules/settlement.md#api-endpoints

The settlement read surface is internal: `settlement:read`. The nullifier status read is what Evidence
uses to decide whether an envelope is duplicate, so it also accepts `evidence:read`. As in Billing, the
demo token→scope map is local to the module so the transport can be deployed without importing another
context's transport layer; a real deployment reads the same mapping from the identity provider.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from collections.abc import Set as AbstractSet

from fastapi import Header, HTTPException, status

from src.shared.domain.errors import ForbiddenError

__all__ = ["require_any_scope", "require_scope"]

#: Demo token → scopes (ADR-005). Mirrors the process-wide demo identity, plus settlement scopes.
_DEMO_TOKENS: dict[str, frozenset[str]] = {
    "demo-owner-token": frozenset(
        {
            "mandate:read",
            "mandate:write",
            "authority:read",
            "evidence:read",
            "settlement:read",
        }
    ),
    "demo-agent-token": frozenset(
        {"billing:propose", "billing:read", "authority:evaluate", "settlement:read"}
    ),
    "demo-payer-token": frozenset({"console:read"}),
}


def _bearer(authorization: str | None) -> frozenset[str]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _DEMO_TOKENS.get(authorization.split(" ", 1)[1].strip(), frozenset())


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
