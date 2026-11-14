"""ADR-005 scope checks for the Authority transport.

Canonical: docs/architecture/decisions/ADR-005-authentication-authorization.md
Reference: docs/architecture/modules/authority.md#api-endpoints

The matrix is small and asymmetric on purpose:

| Scope | Who | Reaches |
|---|---|---|
| `authority:evaluate` | the agent / Rigorix's precondition client | decide, never sign |
| `authority:read` | the owner | intents, verdicts, ledger, inbox |
| `authority:sign` | the owner | submit one signature |
| `settlement:read` | the internal settlement worker | report an outcome |

The agent cannot read the ledger and cannot sign; the owner cannot evaluate. That is the *enforcement*
half of "the agent proposes, the code disposes": a credential that can both decide and sign is a
credential that can pay itself.

The token→scope map is process configuration in this demo (one household), exactly as in Mandate; a real
deployment reads it from the identity provider. The substitution is isolated in `_scopes_for`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Header, HTTPException, status

from src.shared.domain.errors import ForbiddenError

__all__ = ["require_scope"]

#: Demo token → scopes. `authority:sign` belongs to the owner only (A-15: the operator's key is not the
#: owner's signature).
_DEMO_TOKENS: dict[str, frozenset[str]] = {
    "demo-owner-token": frozenset({"authority:read", "authority:sign", "evidence:read"}),
    "demo-agent-token": frozenset({"billing:propose", "billing:read", "authority:evaluate"}),
    "demo-payer-token": frozenset({"console:read"}),
    "demo-settlement-token": frozenset({"settlement:read"}),
}


def _scopes_for(token: str) -> frozenset[str]:
    return _DEMO_TOKENS.get(token, frozenset())


def require_scope(scope: str) -> Callable[..., Awaitable[frozenset[str]]]:
    """Build a dependency that enforces one scope on the bearer token."""

    async def _dependency(authorization: str | None = Header(default=None)) -> frozenset[str]:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = authorization.split(" ", 1)[1].strip()
        scopes = _scopes_for(token)
        if scope not in scopes:
            # A 403 before the service is built: an unauthorized caller never reaches an aggregate.
            raise ForbiddenError(
                f"this credential lacks the {scope} scope",
                required_scope=scope,
                granted=",".join(sorted(scopes)) or "none",
            )
        return scopes

    return _dependency
