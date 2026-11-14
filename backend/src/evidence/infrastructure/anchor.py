"""Anchor gateway and policy adapters.

Canonical: .pi/architecture/modules/evidence.md#ports
Reference: docs/contracts/evidence-contract-freeze.md §2.6

`SqlAnchorGateway` is the **local/demo** implementation of the partnership port. Settlement owns the
chain write in production (`POST /v1/anchors`); this adapter records the anchor it would have
received and returns the same `AnchorReceipt` shape, so the Evidence side can be exercised
end-to-end before Settlement's Phase-B implementation lands. Swapping in the HTTP adapter is a
one-line composition change: the domain only sees `AnchorGateway`.

`write_anchor` is idempotent by hash because `evidence_anchors` has `UNIQUE(envelope_hash)` (E-8). A
replay returns the stored receipt instead of creating a second proof.

`ConfiguredAnchorPolicy` is deliberately dumb: the three modes are frozen, and which one applies is
configuration (ADR-006), not a decision the domain makes at runtime.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from src.evidence.domain.anchor import Anchor
from src.evidence.domain.errors import AnchorMismatch
from src.evidence.domain.ids import AnchorId, new_id
from src.evidence.domain.ports import AnchorGateway, AnchorPolicy, AnchorReceipt
from src.evidence.domain.repositories import AnchorRepository
from src.evidence.domain.values import EnvelopeHash
from src.shared.infrastructure.config import Settings

__all__ = ["ConfiguredAnchorPolicy", "SqlAnchorGateway"]


class SqlAnchorGateway(AnchorGateway):
    """Record anchors locally and read them back (demo seam; Settlement owns the real write)."""

    def __init__(
        self,
        anchors: AnchorRepository,
        *,
        chain_id: int,
        block_number: int = 0,
        tx_prefix: str = "local-anchor",
    ) -> None:
        self._anchors = anchors
        self._chain_id = chain_id
        self._block_number = block_number
        self._tx_prefix = tx_prefix

    async def write_anchor(self, envelope_hash: EnvelopeHash) -> AnchorReceipt:
        existing = await self._anchors.find_for_envelope(envelope_hash)
        if existing is not None:
            return self._receipt(existing)

        anchor = Anchor(
            id=AnchorId(new_id()),
            envelope_hash=envelope_hash,
            anchor_tx=f"{self._tx_prefix}:{envelope_hash.value[:16]}",
            block_number=self._block_number,
            chain_id=self._chain_id,
            anchored_at=datetime.now(UTC),
        )
        try:
            await self._anchors.record(anchor)
        except AnchorMismatch:
            # A concurrent writer recorded the same hash first; the stored anchor is the proof.
            stored = await self._anchors.find_for_envelope(envelope_hash)
            if stored is None:  # pragma: no cover - record() only raises after finding a row
                raise
            return self._receipt(stored)
        return self._receipt(anchor)

    async def read_anchor(self, envelope_hash: EnvelopeHash) -> AnchorReceipt | None:
        existing = await self._anchors.find_for_envelope(envelope_hash)
        return self._receipt(existing) if existing is not None else None

    @staticmethod
    def _receipt(anchor: Anchor) -> AnchorReceipt:
        return AnchorReceipt(
            anchor_tx=anchor.anchor_tx,
            block_number=anchor.block_number,
            chain_id=anchor.chain_id,
        )


class ConfiguredAnchorPolicy(AnchorPolicy):
    """Map an event name to one of the three frozen anchoring modes (ADR-006)."""

    def __init__(
        self,
        default: str = "per_envelope",
        per_event: Mapping[str, str] | None = None,
    ) -> None:
        self._default = default
        self._per_event = dict(per_event or {})

    @classmethod
    def from_settings(cls, settings: Settings) -> ConfiguredAnchorPolicy:
        return cls(default=str(settings.anchor_mode))

    def mode_for(self, event_type: str) -> str:
        return self._per_event.get(event_type, self._default)
