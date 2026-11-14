"""Evidence value objects and closed sets (frozen).

Canonical: docs/architecture/modules/evidence.md#components
Reference: docs/contracts/evidence-contract-freeze.md (E-1, E-6 … E-8)

    EnvelopeHash        hash over canonical bytes + HMAC; the value anchored on-chain (E-1)
    VerificationResult  closed set naming the outcome of a verification (E-6 … E-8)
    Verification        the successful verification record: outcome + anchor tx

`EnvelopeHash` is a value object because two equal hashes are the same proof — there is nothing to
keep identity for. `VerificationResult` is closed on purpose: a verifier that could return an
open-ended string would make the console unable to decide which failure it is rendering.
"""

from __future__ import annotations

import enum
import hashlib
from dataclasses import dataclass

from src.shared.domain.value_object import ValueObject

__all__ = ["EnvelopeHash", "Verification", "VerificationResult"]


@dataclass(frozen=True, slots=True)
class EnvelopeHash(ValueObject):
    """Canonical hash of an envelope including its HMAC (E-1).

    The hash is what gets anchored on-chain and re-compared at verification. Two envelopes with the
    same hash are the same proof; changing one byte of the payload must change it.
    """

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("an envelope hash cannot be empty")

    @classmethod
    def compute(cls, canonical_bytes: bytes, hmac: str) -> EnvelopeHash:
        """Deterministic hash over the exact canonical bytes plus the sealed HMAC (E-1).

        The HMAC is part of the input so a locally re-sealed payload (same fact, different seal) is a
        different on-chain value. Separator byte keeps the two inputs unambiguous.

        Raises:
            ValueError: the canonical bytes are empty (there is no fact to hash).
        """
        if not canonical_bytes:
            raise ValueError("cannot hash an envelope with no canonical bytes")
        digest = hashlib.sha256(canonical_bytes + b"|" + hmac.encode("utf-8")).hexdigest()
        return cls(digest)


class VerificationResult(enum.StrEnum):
    """Closed set of verification outcomes (E-6 … E-8).

    `VERIFIED` is the only success. `HMAC_MISMATCH` and `ANCHOR_MISMATCH` are different failures
    because they name different tampering: local edits versus a rewritten anchor reference.
    `UNANCHORED` is not tampering — it is an envelope whose anchor has not been written yet.
    """

    VERIFIED = "VERIFIED"
    HMAC_MISMATCH = "HMAC_MISMATCH"
    ANCHOR_MISMATCH = "ANCHOR_MISMATCH"
    UNANCHORED = "UNANCHORED"


@dataclass(frozen=True, slots=True)
class Verification(ValueObject):
    """The record returned by `EvidenceEnvelope.verify` when it succeeds (E-6).

    `failing_field` is `None` on success; failures are raised as `HmacMismatch` / `AnchorMismatch`
    so the refusal vocabulary, not a boolean, is what callers handle.
    """

    result: VerificationResult
    failing_field: str | None = None
    anchor_tx: str | None = None
