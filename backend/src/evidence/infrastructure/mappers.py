"""Row ⇄ domain translation — the seam that keeps ORM types out of the model.

Canonical: docs/architecture/modules/evidence.md#persistence-contract
Reference: docs/contracts/evidence-contract-freeze.md §2.5

Two rules:

1. An envelope is rehydrated **as it was sealed**. `canonical_bytes()` is recomputed from the stored
   fields, so a row that no longer produces its HMAC fails verification rather than being repaired
   on read.
2. Timestamps are normalised to UTC-aware datetimes. SQLite drops the offset on read, and a naive
   datetime would produce different canonical bytes than the one that was sealed (E-1).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from src.evidence.domain.anchor import Anchor
from src.evidence.domain.evidence_envelope import EvidenceEnvelope
from src.evidence.domain.ids import AnchorId, EnvelopeId
from src.evidence.domain.values import EnvelopeHash
from src.evidence.infrastructure.models import AnchorRow, EnvelopeRow

__all__ = [
    "anchor_to_domain",
    "anchor_to_row",
    "envelope_to_domain",
    "envelope_to_row",
    "payload_from_json",
    "payload_to_json",
]


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes; the sealed bytes require an explicit UTC offset."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def payload_to_json(payload: dict[str, Any]) -> str:
    """Stable JSON for the fact payload — sorted keys so a re-read reproduces the bytes."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def payload_from_json(raw: str) -> dict[str, Any]:
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise ValueError("an evidence payload must be a JSON object")
    return loaded


def envelope_to_domain(row: EnvelopeRow) -> EvidenceEnvelope:
    return EvidenceEnvelope(
        id=EnvelopeId(row.id),
        event_type=row.event_type,
        subject_intent_id=row.subject_intent_id,
        subject_invoice_id=row.subject_invoice_id,
        subject_payee_id=row.subject_payee_id,
        payload=payload_from_json(row.payload),
        constitution_version=row.constitution_version,
        actor=row.actor,
        occurred_at=_aware(row.occurred_at),
        hmac=row.hmac,
        previous_hash=row.previous_hash,
        anchor_mode=row.anchor_mode,
    )


def envelope_to_row(envelope: EvidenceEnvelope) -> EnvelopeRow:
    return EnvelopeRow(
        id=str(envelope.id),
        event_type=envelope.event_type,
        subject_intent_id=envelope.subject_intent_id,
        subject_invoice_id=envelope.subject_invoice_id,
        subject_payee_id=envelope.subject_payee_id,
        payload=payload_to_json(dict(envelope.payload)),
        constitution_version=envelope.constitution_version,
        actor=envelope.actor,
        occurred_at=envelope.occurred_at,
        hmac=envelope.hmac,
        previous_hash=envelope.previous_hash,
        anchor_mode=envelope.anchor_mode,
    )


def anchor_to_domain(row: AnchorRow) -> Anchor:
    return Anchor(
        id=AnchorId(row.id),
        envelope_hash=EnvelopeHash(row.envelope_hash),
        anchor_tx=row.anchor_tx,
        block_number=row.block_number,
        chain_id=row.chain_id,
        anchored_at=_aware(row.anchored_at),
    )


def anchor_to_row(anchor: Anchor) -> AnchorRow:
    return AnchorRow(
        id=str(anchor.id),
        envelope_hash=anchor.envelope_hash.value,
        anchor_tx=anchor.anchor_tx,
        block_number=anchor.block_number,
        chain_id=anchor.chain_id,
        anchored_at=anchor.anchored_at,
    )
