"""ADR-005 scope checks for the console transport.

Canonical: docs/architecture/decisions/ADR-005-authentication-authorization.md
Reference: docs/architecture/modules/console.md#api-endpoints

The console's only write is `POST /v1/console/approvals/{id}/signature`, so its scope map is small:
an owner token may read the owner surfaces and sign, a payer token may only read bills. The map is
local to the console (like Evidence's) so the module can be deployed without importing another
context's transport layer. The owner token deliberately carries `authority:sign` and nothing that
names an intent, attempt or settlement order (CON-04).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Header, HTTPException, status

from src.shared.domain.errors import ForbiddenError

__all__ = ["bearer_token", "require_scope"]

_DEMO_TOKENS: dict[str, frozenset[str]] = {
    "demo-owner-token": frozenset(
        {"authority:read", "authority:sign", "console:read", "evidence:read", "mandate:read"}
    ),
    "demo-payer-token": frozenset({"console:read", "billing:read"}),
    "demo-agent-token": frozenset({"billing:propose", "billing:read", "authority:evaluate"}),
}


def _scopes_for(token: str) -> frozenset[str]:
    return _DEMO_TOKENS.get(token, frozenset())


def bearer_token(authorization: str | None) -> str:
    """The raw token, used as the owner/payer scope forwarded to an upstream port."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return authorization.split(" ", 1)[1].strip()


def require_scope(scope: str) -> Callable[..., Awaitable[frozenset[str]]]:
    """Build a dependency that enforces one scope on the bearer token."""

    async def _dependency(authorization: str | None = Header(default=None)) -> frozenset[str]:
        scopes = _scopes_for(bearer_token(authorization))
        if scope not in scopes:
            raise ForbiddenError(
                f"this credential lacks the {scope} scope",
                required_scope=scope,
                granted=",".join(sorted(scopes)) or "none",
            )
        return scopes

    return _dependency
