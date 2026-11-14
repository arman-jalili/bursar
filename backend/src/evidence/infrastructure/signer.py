"""HMAC signer — the only adapter that touches the operator-held key (E-9).

Canonical: .pi/architecture/decisions/ADR-005-authentication-authorization.md
Reference: docs/contracts/evidence-contract-freeze.md §2.6

The key is read from `BURSAR_HMAC_KEY` at boot and kept inside this object. It is never passed to an
envelope, never written to a row, and never logged — `repr` is overridden so an accidental
`logger.info(..., extra={"signer": signer})` cannot leak it.

`verify` uses `hmac.compare_digest`: a byte-by-byte early exit would leak the distance to a valid
MAC, which is exactly the oracle a tampering attempt wants.
"""

from __future__ import annotations

import hashlib
import hmac

from src.evidence.domain.errors import SigningUnavailable
from src.shared.infrastructure.config import Settings

__all__ = ["HmacSigner"]


class HmacSigner:
    """`EnvelopeSigner` adapter: HMAC-SHA256 over the envelope's canonical bytes."""

    def __init__(self, key: str | bytes) -> None:
        raw = key.encode("utf-8") if isinstance(key, str) else key
        if not raw:
            raise SigningUnavailable("BURSAR_HMAC_KEY is not set")
        self._key = raw

    @classmethod
    def from_settings(cls, settings: Settings) -> HmacSigner:
        """Build the signer from operator config. The secret is revealed only here."""
        return cls(settings.hmac_key.get_secret_value())

    def sign(self, canonical_bytes: bytes) -> str:
        try:
            return hmac.new(self._key, canonical_bytes, hashlib.sha256).hexdigest()
        except Exception as exc:  # pragma: no cover - hashlib failures are environmental
            raise SigningUnavailable("the HMAC signer could not seal the fact") from exc

    def verify(self, canonical_bytes: bytes, hmac_hex: str) -> bool:
        expected = hmac.new(self._key, canonical_bytes, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, hmac_hex)

    def __repr__(self) -> str:
        """Never print the key, even from a debugger or a structured log."""
        return "HmacSigner(key=<redacted>)"
