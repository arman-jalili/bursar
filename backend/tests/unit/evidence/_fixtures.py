"""Shared fixtures and test doubles for the Evidence contract suites.

Canonical: docs/contracts/evidence-contract-freeze.md §1
Reference: docs/architecture/modules/evidence.md#acceptance-criteria

Only helpers live here — no tests. The doubles implement the frozen ports closely enough that a
behaviour test can drive `SealEvidence` once Phase B replaces the stub body; today every call into a
stubbed method raises `NotImplementedError`, which is the red state the freeze requires.
"""

from __future__ import annotations

import hashlib
import hmac as hmaclib
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from src.evidence.domain.anchor import Anchor
from src.evidence.domain.errors import SigningUnavailable
from src.evidence.domain.evidence_envelope import EvidenceEnvelope
from src.evidence.domain.ids import AnchorId, EnvelopeId, EventId, new_id
from src.evidence.domain.ports import AnchorReceipt, ExpectedEvent
from src.evidence.domain.values import EnvelopeHash

__all__ = [
    "AcceptingSigner",
    "FailingSigner",
    "FakeAnchorGateway",
    "FakeEnvelopeStore",
    "FakeExpectedEvents",
    "FakeProcessedEvents",
    "HmacSigner",
    "RefusingSigner",
    "StaticPolicy",
    "an_anchor",
    "an_envelope",
]


def an_envelope(**overrides: Any) -> EvidenceEnvelope:
    """A representative sealed refusal envelope; overrides let a test tamper with one field."""
    values: dict[str, Any] = {
        "id": EnvelopeId(new_id()),
        "event_type": "PaymentRefused",
        "subject_intent_id": "intent-1",
        "subject_invoice_id": "invoice-1",
        "subject_payee_id": "payee-1",
        "payload": {
            "amount_micro_usdc": 42_500_000,
            "reason_codes": ["cap_exceeded"],
        },
        "constitution_version": "3",
        "actor": "authority",
        "occurred_at": datetime(2026, 11, 13, 12, 0, tzinfo=UTC),
        "hmac": "hmac-deadbeef",
        "previous_hash": None,
        "anchor_mode": "per_envelope",
    }
    values.update(overrides)
    return EvidenceEnvelope(**values)


def an_anchor(envelope_hash: EnvelopeHash, *, anchor_tx: str = "0xanchor") -> Anchor:
    return Anchor(
        id=AnchorId(new_id()),
        envelope_hash=envelope_hash,
        anchor_tx=anchor_tx,
        block_number=19_000_000,
        chain_id=31337,
        anchored_at=datetime(2026, 11, 13, 12, 1, tzinfo=UTC),
    )


class HmacSigner:
    """A real HMAC adapter for tests; keeps the key inside the signer (E-9)."""

    def __init__(self, key: str) -> None:
        self._key = key.encode()

    def sign(self, canonical_bytes: bytes) -> str:
        return hmaclib.new(self._key, canonical_bytes, hashlib.sha256).hexdigest()

    def verify(self, canonical_bytes: bytes, sealed: str) -> bool:
        return hmaclib.compare_digest(self.sign(canonical_bytes), sealed)


class AcceptingSigner:
    def sign(self, canonical_bytes: bytes) -> str:
        return "accepted-hmac"

    def verify(self, canonical_bytes: bytes, sealed: str) -> bool:
        return True


class RefusingSigner:
    def sign(self, canonical_bytes: bytes) -> str:
        return "refused-hmac"

    def verify(self, canonical_bytes: bytes, sealed: str) -> bool:
        return False


class FailingSigner:
    """Signer outage: witness-only means this becomes a gap, never a publisher error (E-10)."""

    def sign(self, canonical_bytes: bytes) -> str:
        raise SigningUnavailable("signer down")

    def verify(self, canonical_bytes: bytes, sealed: str) -> bool:
        raise SigningUnavailable("signer down")


class StaticPolicy:
    def mode_for(self, event_type: str) -> str:
        return "per_envelope"


class FakeEnvelopeStore:
    def __init__(self) -> None:
        self.appended: list[EvidenceEnvelope] = []

    async def append(self, envelope: EvidenceEnvelope) -> None:
        self.appended.append(envelope)

    async def find_by_id(self, id_: EnvelopeId) -> EvidenceEnvelope | None:
        return next((e for e in self.appended if e.id == id_), None)

    async def list_for_subject(
        self,
        *,
        intent_id: str | None = None,
        invoice_id: str | None = None,
        payee_id: str | None = None,
        limit: int = 50,
    ) -> Sequence[EvidenceEnvelope]:
        return tuple(self.appended[:limit])


class FakeProcessedEvents:
    def __init__(self) -> None:
        self.claimed: set[tuple[str, str]] = set()

    async def claim(self, event_id: EventId, handler: str) -> bool:
        key = (str(event_id), handler)
        if key in self.claimed:
            return False
        self.claimed.add(key)
        return True

    async def is_processed(self, event_id: EventId, handler: str) -> bool:
        return (str(event_id), handler) in self.claimed


class FakeAnchorGateway:
    def __init__(self) -> None:
        self.written: list[EnvelopeHash] = []

    async def write_anchor(self, envelope_hash: EnvelopeHash) -> AnchorReceipt:
        self.written.append(envelope_hash)
        return AnchorReceipt(anchor_tx="0xanchor", block_number=19_000_000, chain_id=31337)

    async def read_anchor(self, envelope_hash: EnvelopeHash) -> AnchorReceipt | None:
        return None


class FakeExpectedEvents:
    def __init__(self, events: Sequence[ExpectedEvent]) -> None:
        self._events = tuple(events)

    async def expected(self, *, since: datetime, until: datetime) -> Sequence[ExpectedEvent]:
        return self._events
