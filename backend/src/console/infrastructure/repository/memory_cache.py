"""In-process TTL cache for projected read models (concrete `ReadModelCache`, CON-01/CON-02).

Canonical: docs/architecture/modules/console.md#architecture
Reference: docs/contracts/console-contract-freeze.md §2.6

The cache stores **projected** values only — the caller is expected to hand it the output of a
surface projection, never a raw upstream payload. It exposes no enumeration and cannot be cleared:
the TTL is the only expiry rule and `invalidate` exists for the one owner action that makes a view
provably stale.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from types import MappingProxyType

__all__ = ["InMemoryReadModelCache"]


class InMemoryReadModelCache:
    """TTL-bounded mapping. Not thread-safe by itself; the console is single-process asyncio."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._entries: dict[str, tuple[Mapping[str, object], float]] = {}

    def get(self, key: str) -> Mapping[str, object] | None:
        """Return the cached projection or None; never raises for absence (CON-02)."""
        entry = self._entries.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if self._clock() >= expires_at:
            # Expiry is lazy: no background task owns the cache's lifetime.
            self._entries.pop(key, None)
            return None
        return value

    def put(self, key: str, value: Mapping[str, object], ttl_seconds: int) -> None:
        """Store a projection with a TTL; the value must already be whitelisted (CON-01)."""
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive; use invalidate() to drop an entry")
        # Copy + freeze: a caller mutating its dict afterwards must not rewrite the cached view.
        frozen = MappingProxyType(dict(value))
        self._entries[key] = (frozen, self._clock() + ttl_seconds)

    def invalidate(self, key: str) -> None:
        """Drop one entry after an owner action makes it stale (CON-02)."""
        self._entries.pop(key, None)
