"""Evidence repository ports — owned by `domain/` (frozen).

Canonical: .pi/architecture/modules/evidence.md#persistence-contract
Reference: docs/contracts/evidence-contract-freeze.md §2.5

    EnvelopeRepository        append · find_by_id · list_for_subject      (no update, no delete)
    AnchorRepository          record · find_for_envelope                  (no update, no delete)
    ProcessedEventRepository  claim                                       (idempotency key)

Two rules are expressed by the signatures rather than left to convention:

1. **There is no `save`.** `EnvelopeRepository` deliberately does **not** extend the shared
   `Repository[Id, Aggregate]` port, because that base declares `save` — an update path. E-5 says a
   sealed envelope is never rewritten; the type system should make the update path unavailable, not
   merely undocumented. A correction is `append` of a new envelope whose `previous_hash` links it.
2. **No transaction control.** No `commit`, `flush` or `begin`: the unit of work belongs to the
   application layer (ADR-002), which is what makes "one delivery = one atomic claim + append"
   checkable.

`claim` is the idempotency primitive (E-4): it atomically records `(event_id, handler)` and returns
`True` only for the first delivery. Returning a bool rather than raising on replay is deliberate —
a duplicate delivery is normal at-least-once behaviour, not a refusal.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from src.evidence.domain.anchor import Anchor
from src.evidence.domain.evidence_envelope import EvidenceEnvelope
from src.evidence.domain.ids import EnvelopeId, EventId
from src.evidence.domain.values import EnvelopeHash

__all__ = ["AnchorRepository", "EnvelopeRepository", "ProcessedEventRepository"]


class EnvelopeRepository(ABC):
    """Append-only persistence for envelopes (E-5). No `save`, no update, no delete."""

    @abstractmethod
    async def append(self, envelope: EvidenceEnvelope) -> None:
        """Insert a newly sealed envelope. Never overwrites; a duplicate id is a bug.

        Raises:
            AppendOnlyViolation: an envelope with this id already exists (E-5).
        """
        raise NotImplementedError("E-5 — see module doc")

    @abstractmethod
    async def find_by_id(self, id_: EnvelopeId) -> EvidenceEnvelope | None:
        """Return the envelope or None. Never raises for absence (E-6)."""
        raise NotImplementedError("E-6 — see module doc")

    @abstractmethod
    async def list_for_subject(
        self,
        *,
        intent_id: str | None = None,
        invoice_id: str | None = None,
        payee_id: str | None = None,
        limit: int = 50,
    ) -> Sequence[EvidenceEnvelope]:
        """The audit read model. Ordered oldest-first so the `previous_hash` chain is readable."""
        raise NotImplementedError("E-5 — see module doc")


class AnchorRepository(ABC):
    """Persistence for on-chain anchors. One row per `envelope_hash` (E-8)."""

    @abstractmethod
    async def record(self, anchor: Anchor) -> None:
        """Insert the anchor for a hash.

        Raises:
            AnchorMismatch: this envelope hash already has a *different* anchor record (E-8).
        """
        raise NotImplementedError("E-8 — see module doc")

    @abstractmethod
    async def find_for_envelope(self, envelope_hash: EnvelopeHash) -> Anchor | None:
        """The anchor for this exact hash, or None (E-8)."""
        raise NotImplementedError("E-8 — see module doc")


class ProcessedEventRepository(ABC):
    """Idempotency store keyed by `(event_id, handler)` (E-4)."""

    @abstractmethod
    async def claim(self, event_id: EventId, handler: str) -> bool:
        """Atomically claim a delivery.

        Returns:
            True the first time this `(event_id, handler)` is seen; False on every replay.

        Raises:
            AppendOnlyViolation: the adapter was asked to overwrite an existing claim.
        """
        raise NotImplementedError("E-4 — see module doc")

    @abstractmethod
    async def is_processed(self, event_id: EventId, handler: str) -> bool:
        """Read-only check used by the witness-gap report (E-10). Never mutates."""
        raise NotImplementedError("E-10 — see module doc")
