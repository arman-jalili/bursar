"""Evidence commands and results (frozen) — the shape every caller codes against.

Canonical: .pi/architecture/modules/evidence.md#application-services
Reference: docs/contracts/evidence-contract-freeze.md §2.7

* `SealEvidenceCommand` carries a `DomainEvent` and an actor. It has no field for an HMAC key, a
  canonical-bytes override or an anchor hash: the type is the first line of E-9 and E-8.
* `SealEvidenceResult.witness_gap` is how E-10 leaves the handler without raising: a witness that
  could not do its job reports the fact, and the publisher continues.
* `VerifyEvidenceResult` mirrors the HTTP body (`result`, optional `field`, optional `anchor_tx`)
  so the router does no translation beyond serialising it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.evidence.domain.values import VerificationResult
from src.shared.domain.event import DomainEvent

__all__ = [
    "EnvelopeView",
    "SealEvidenceCommand",
    "SealEvidenceResult",
    "VerifyEvidenceCommand",
    "VerifyEvidenceResult",
]


@dataclass(frozen=True, slots=True)
class EnvelopeView:
    """An envelope as the API exposes it. `full=0` may omit the payload; the id and hash never.

    `payload` is `None` on list responses (the default) and populated only when the caller asks for
    `?full=1`. The sealed bytes are unaffected: the read model is the envelope, not the other way
    round, so omitting the payload here never changes `hmac` or `envelope_hash`.
    """

    envelope_id: str
    event_type: str
    subject_intent_id: str | None
    subject_invoice_id: str | None
    subject_payee_id: str | None
    constitution_version: str | None
    actor: str
    occurred_at: datetime
    hmac: str
    previous_hash: str | None
    anchor_mode: str
    envelope_hash: str
    anchor_tx: str | None = None
    #: Present only on `?full=1`; the list read model deliberately omits the fact's body.
    payload: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class SealEvidenceCommand:
    """Seal one delivered fact (FR-022). The event is the publisher's; Evidence never edits it."""

    event: DomainEvent
    actor: str
    anchor_mode: str = "per_envelope"


@dataclass(frozen=True, slots=True)
class SealEvidenceResult:
    """What the subscriber records after one delivery (E-2, E-4, E-10)."""

    envelope_id: str
    event_id: str
    envelope_hash: str
    anchor_tx: str | None = None
    sealed: bool = True
    duplicate: bool = False
    #: Set when signing or anchoring failed; the fact is still published, the witness is behind.
    witness_gap: str | None = None


@dataclass(frozen=True, slots=True)
class VerifyEvidenceCommand:
    """Re-verify one envelope for the console or an auditor (FR-023)."""

    envelope_id: str


@dataclass(frozen=True, slots=True)
class VerifyEvidenceResult:
    """The verify response body: `200` when `VERIFIED`, `409` otherwise (E-6 … E-8)."""

    result: VerificationResult
    failing_field: str | None = None
    anchor_tx: str | None = None
