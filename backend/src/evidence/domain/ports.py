"""Evidence ports — the narrow interfaces the application layer depends on (frozen).

Canonical: .pi/architecture/modules/evidence.md#ports
Reference: docs/contracts/evidence-contract-freeze.md §2.6

Four ports, each keeping a foreign concern out of the domain:

`EnvelopeSigner` — HMAC over canonical bytes. The key is operator-held (ADR-005) and the port is the
only thing that touches it. A future KMS adapter swaps behind the same two methods; the envelope
never receives the key, which is what makes E-9 structural rather than a code review.

`AnchorGateway` — the partnership edge to Settlement. Evidence never writes the chain itself:
Settlement owns `POST /v1/anchors`, and this port is the ACL that hides it. `write_anchor` is
idempotent by `envelope_hash` because the DB enforces `UNIQUE(envelope_hash)`.

`AnchorPolicy` — the strategy (`per_envelope | batched | demo_only`, ADR-006). The mode is recorded on
the envelope, so a batched demo cannot later look individually anchored.

`ExpectedEventsPort` — the read side of witness-only. Given a window, which `event_id`s should have
been sealed? A missing id becomes a visible gap instead of an exception that blocks dispatch (E-10).

Ports are Protocols, not ABCs: the domain only needs the shape, and adapters live in `infrastructure/`
(Phase B). None carries transaction control — the unit of work belongs to `application/` (ADR-002).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from src.evidence.domain.ids import EventId
from src.evidence.domain.values import EnvelopeHash

__all__ = [
    "AnchorGateway",
    "AnchorPolicy",
    "AnchorReceipt",
    "EnvelopeSigner",
    "ExpectedEvent",
    "ExpectedEventsPort",
]


@dataclass(frozen=True, slots=True)
class AnchorReceipt:
    """What Settlement returns after writing an anchor (E-8).

    `anchor_tx` is the on-chain transaction, `block_number` the confirmation height, `chain_id` the
    network. The tuple is the independent proof; an anchor without a tx is not an anchor.
    """

    anchor_tx: str
    block_number: int
    chain_id: int


@dataclass(frozen=True, slots=True)
class ExpectedEvent:
    """One fact that should have been sealed in a window (E-10)."""

    event_id: EventId
    event_type: str
    occurred_at: datetime


class EnvelopeSigner(Protocol):
    """HMAC strategy. The key lives inside the adapter, never in an envelope (E-9)."""

    def sign(self, canonical_bytes: bytes) -> str:
        """Return the HMAC for exactly these bytes.

        Raises:
            SigningUnavailable: the key is missing or the signer cannot operate (E-10).
        """
        raise NotImplementedError("E-2 — see module doc")

    def verify(self, canonical_bytes: bytes, hmac: str) -> bool:
        """Constant-time comparison of the recomputed HMAC with the sealed one (E-2, E-7)."""
        raise NotImplementedError("E-2 — see module doc")


class AnchorGateway(Protocol):
    """The Settlement-owned anchor write/read (ADR-007). Evidence never signs chain transactions."""

    async def write_anchor(self, envelope_hash: EnvelopeHash) -> AnchorReceipt:
        """Anchor exactly this hash. Idempotent by hash — a replay returns the same receipt.

        Raises:
            AnchoringUnavailable: Settlement or the chain is unreachable (E-10).
        """
        raise NotImplementedError("E-8 — see module doc")

    async def read_anchor(self, envelope_hash: EnvelopeHash) -> AnchorReceipt | None:
        """The receipt for this hash, or None when it was never anchored (E-6, E-8)."""
        raise NotImplementedError("E-6 — see module doc")


class AnchorPolicy(Protocol):
    """Which anchoring mode applies to a fact (ADR-006). Recorded on every envelope, never guessed."""

    def mode_for(self, event_type: str) -> str:
        """Return `per_envelope`, `batched` or `demo_only` for this wire event name."""
        raise NotImplementedError("E-2 — see module doc")


class ExpectedEventsPort(Protocol):
    """Read the facts that *should* have a witness, so a gap can be reported after the fact (E-10)."""

    async def expected(self, *, since: datetime, until: datetime) -> Sequence[ExpectedEvent]:
        """Return publisher facts in the window. Never raises for an empty window."""
        raise NotImplementedError("E-10 — see module doc")
