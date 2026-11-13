"""EvidenceEnvelope — the signed, immutable wrapper around one domain fact (frozen).

Canonical: .pi/architecture/modules/evidence.md#components-evidenceenvelope
Reference: docs/contracts/evidence-contract-freeze.md (E-1 … E-9)

    E-1  canonical encoding is byte-deterministic across runs and key orderings
    E-2  every delivered event yields exactly one envelope with a valid HMAC
    E-3  a refusal has the same shape as a settlement — not a lesser record
    E-5  envelopes are append-only; a correction is a new envelope linked by `previous_hash`
    E-7  one changed payload byte invalidates the HMAC and names the failing field
    E-9  the HMAC key never appears in the sealed bytes, the payload or the hmac

`frozen=True, slots=True` makes E-5 and E-1 structural: there is no setter, and `payload` is a
mapping the canonical encoder must sort rather than trust insertion order. `canonical_bytes` is
deliberately a method on the envelope, not on an adapter: verification is only meaningful if the
bytes are reproducible in the domain.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.evidence.domain.anchor import Anchor
from src.evidence.domain.ids import EnvelopeId, new_id
from src.evidence.domain.ports import EnvelopeSigner
from src.evidence.domain.values import EnvelopeHash, Verification
from src.shared.domain.event import DomainEvent

__all__ = ["EvidenceEnvelope"]


@dataclass(frozen=True, slots=True)
class EvidenceEnvelope:
    """One signed fact. Identity persists; the contents never change after sealing."""

    id: EnvelopeId
    event_type: str
    subject_intent_id: str | None
    subject_invoice_id: str | None
    subject_payee_id: str | None
    payload: Mapping[str, Any]
    constitution_version: str | None
    actor: str
    occurred_at: datetime
    hmac: str
    previous_hash: str | None
    anchor_mode: str

    @classmethod
    def from_event(
        cls,
        event: DomainEvent,
        *,
        signer: EnvelopeSigner,
        actor: str,
        previous_hash: str | None = None,
        anchor_mode: str = "per_envelope",
    ) -> EvidenceEnvelope:
        """Seal one delivered fact into an envelope (E-2, E-3, E-9).

        Subjects and constitution version are read from the event payload (`intent_id`,
        `invoice_id`, `payee_id`, `constitution_version`); a missing one stays `None` rather than an
        empty string, so "not applicable" and "empty" are distinguishable on the wire.

        Raises:
            SigningUnavailable: the signer could not produce an HMAC (E-10).
            ValueError: the event payload cannot be canonically encoded (non-JSON value).
        """
        raise NotImplementedError("E-2 — see module doc")

    def canonical_bytes(self) -> bytes:
        """Deterministic encoding: sorted keys, no floats, explicit nulls, compact separators (E-1).

        The bytes cover the fact and its chain link, but **not** the id or the HMAC itself: a replay
        with a fresh id must not change the sealed bytes of an identical fact.
        """
        raise NotImplementedError("E-1 — see module doc")

    def hash(self) -> EnvelopeHash:
        """The value anchored on-chain: hash over `canonical_bytes()` plus the sealed HMAC (E-1)."""
        raise NotImplementedError("E-1 — see module doc")

    def hmac_is_valid(self, signer: EnvelopeSigner) -> bool:
        """Recompute the HMAC over the bytes as they are now and compare (E-2, E-7)."""
        raise NotImplementedError("E-2 — see module doc")

    def verify(self, signer: EnvelopeSigner, anchor: Anchor | None) -> Verification:
        """Re-verify this envelope against its HMAC and its anchor (E-6 … E-8).

        Returns:
            `Verification(VERIFIED, anchor_tx=…)` when both checks pass.
            `Verification(UNANCHORED)` when no anchor exists yet — not a tamper failure.

        Raises:
            HmacMismatch: the recomputed HMAC differs; `field` names the sealed field that failed.
            AnchorMismatch: the anchor belongs to a different envelope hash.
        """
        raise NotImplementedError("E-6 — see module doc")

    def corrected(
        self,
        event: DomainEvent,
        *,
        signer: EnvelopeSigner,
        actor: str,
        anchor_mode: str = "per_envelope",
    ) -> EvidenceEnvelope:
        """Append a correction as a **new** envelope linked by `previous_hash` (E-5).

        The original is never rewritten. A correction that reused the id would make the chain a lie:
        the old hash would still be anchored and the row behind it would no longer produce it.
        """
        raise NotImplementedError("E-5 — see module doc")

    @classmethod
    def with_id(cls, envelope_id: EnvelopeId | None = None) -> EnvelopeId:
        """Allocate an envelope identity (the uuid factory is the one non-stub exception, E-5)."""
        return envelope_id or EnvelopeId(new_id())
