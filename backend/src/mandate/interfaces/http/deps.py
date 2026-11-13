"""ADR-005 scope checks for the Mandate transport.

Canonical: .pi/architecture/decisions/ADR-005-authentication-authorization.md
Reference: .pi/architecture/modules/mandate.md#api-endpoints

Two layers, and the second one is the point:

1. **Scope** — a bearer token must carry the scope the endpoint needs. The agent key holds
   `billing:propose` only, so it cannot reach any Mandate write endpoint: refusal happens here, before
   an aggregate is loaded.
2. **Owner proof** — for changing rules or bank details, possession of a key is not enough; the
   caller must present the owner's EIP-712 signature. Phase-3 wiring verifies it against the intent;
   Mandate only asks whether *this* change is covered.

The token→scopes map is process configuration in this demo (one household); a real deployment would
read it from the identity provider. That substitution is isolated in `_scopes_for`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Header, HTTPException, status

from src.shared.domain.errors import ForbiddenError

__all__ = ["require_owner_proof", "require_scope"]

#: Demo token → scopes. The agent token deliberately has no `mandate:*` scope (NFR-016).
_DEMO_TOKENS: dict[str, frozenset[str]] = {
    "demo-owner-token": frozenset(
        {"mandate:read", "mandate:write", "authority:read", "evidence:read"}
    ),
    "demo-agent-token": frozenset({"billing:propose", "billing:read", "authority:evaluate"}),
    "demo-payer-token": frozenset({"console:read"}),
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
            raise ForbiddenError(
                f"this credential lacks the {scope} scope",
                required_scope=scope,
                granted=",".join(sorted(scopes)) or "none",
            )
        return scopes

    return _dependency


def require_owner_proof(proof: str) -> None:
    """Layer 2: a state-changing owner action needs a signature, not just a key.

    The HTTP layer verifies the EIP-712 signature before this point; an empty proof means the caller
    did not even attempt to sign, which is a plain 403 rather than a mismatch.
    """
    if not proof:
        raise ForbiddenError("this change requires the owner's signature", missing="owner_proof")
