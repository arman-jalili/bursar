"""Anchor — the on-chain record of one envelope hash (frozen).

Canonical: docs/architecture/modules/evidence.md#components
Reference: docs/contracts/evidence-contract-freeze.md (E-8)

An anchor is an **entity**, not a value object, because it has identity that persists: one row per
envelope hash with its own transaction, block and chain. It is kept as captured — not promoted to an
aggregate — because the interesting rule is a single comparison (`matches`), not a lifecycle.

`UNIQUE(envelope_hash)` in `evidence_anchors` is the storage mirror of that comparison: the same hash
cannot be anchored twice, and a different hash cannot masquerade as this envelope's proof.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.evidence.domain.ids import AnchorId
from src.evidence.domain.values import EnvelopeHash

__all__ = ["Anchor"]


@dataclass(frozen=True, slots=True)
class Anchor:
    """One on-chain write of one envelope hash. Immutable once recorded (E-8)."""

    id: AnchorId
    envelope_hash: EnvelopeHash
    anchor_tx: str
    block_number: int
    chain_id: int
    anchored_at: datetime

    def matches(self, envelope_hash: EnvelopeHash) -> bool:
        """True only when this anchor recorded exactly `envelope_hash` (E-8).

        A mismatch is a verification failure, not an "anchor for another envelope" convenience:
        accepting it would let a tampered row borrow a valid on-chain proof.
        """
        return self.envelope_hash == envelope_hash
