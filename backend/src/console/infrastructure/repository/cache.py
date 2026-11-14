"""Read-model cache port (frozen) — TTL only, no enumeration, no commit (CON-02).

Canonical: docs/architecture/modules/console.md#architecture
Reference: docs/contracts/console-contract-freeze.md §2.6

The console owns **no tables**. The cache holds projected views, never raw upstream payloads: a raw
payload cached across a deployment would be re-projected with a newer whitelist against an older
shape, which is exactly how an un-whitelisted field reaches a screen.

There is no `clear()` and no iteration. A cache the console can enumerate is a second store of
upstream truth; the TTL is the only expiry rule, and `invalidate` exists for the one case where an
owner action makes a view provably stale.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

__all__ = ["ReadModelCache"]


class ReadModelCache(Protocol):
    """In-process, TTL-bounded cache for projected read models."""

    def get(self, key: str) -> Mapping[str, object] | None:
        """Return the cached projection or None; never raises for absence (CON-02)."""
        raise NotImplementedError("CON-02 — see module doc")

    def put(self, key: str, value: Mapping[str, object], ttl_seconds: int) -> None:
        """Store a projection with a TTL; the value must already be whitelisted (CON-01)."""
        raise NotImplementedError("CON-02 — see module doc")

    def invalidate(self, key: str) -> None:
        """Drop one entry after an owner action makes it stale (CON-02)."""
        raise NotImplementedError("CON-02 — see module doc")
