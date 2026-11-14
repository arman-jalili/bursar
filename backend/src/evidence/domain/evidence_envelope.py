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

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from src.evidence.domain.anchor import Anchor
from src.evidence.domain.errors import AnchorMismatch, HmacMismatch
from src.evidence.domain.ids import EnvelopeId, new_id
from src.evidence.domain.ports import EnvelopeSigner
from src.evidence.domain.values import EnvelopeHash, Verification, VerificationResult
from src.shared.domain.event import DomainEvent

__all__ = ["EvidenceEnvelope"]


def _normalise(value: Any) -> Any:
    """Recursively turn a payload into a JSON-safe, order-stable value (E-1).

    Mappings become plain dicts (``sort_keys`` then fixes their order), tuples/sets become lists, and
    dates/enums/decimals get a lossless string form. Floats are refused: the canonical contract is
    integer micro-units, and a float's text form is the one place a re-serialisation can drift.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        raise ValueError("canonical encoding refuses floats; use integer micro-units")
    if isinstance(value, Mapping):
        return {str(k): _normalise(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalise(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return [_normalise(v) for v in sorted(value, key=repr)]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return _normalise(value.value)
    if isinstance(value, Decimal):
        return str(value)
    raise ValueError(f"canonical encoding cannot represent {type(value).__name__}")


def _subject(payload: Mapping[str, Any], field: str) -> str | None:
    """A subject id from the publisher's payload; absent stays None, never an empty string."""
    value = payload.get(field)
    return None if value is None else str(value)


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
        payload = dict(event.to_payload())
        occurred_at = event.occurred_at
        if occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")

        constitution_version = payload.get("constitution_version")
        unsigned = cls(
            id=cls.with_id(),
            event_type=event.event_name,
            subject_intent_id=_subject(payload, "intent_id"),
            subject_invoice_id=_subject(payload, "invoice_id"),
            subject_payee_id=_subject(payload, "payee_id"),
            payload=payload,
            constitution_version=(
                None if constitution_version is None else str(constitution_version)
            ),
            actor=actor,
            occurred_at=occurred_at,
            hmac="",
            previous_hash=previous_hash,
            anchor_mode=anchor_mode,
        )
        return replace(unsigned, hmac=signer.sign(unsigned.canonical_bytes()))

    def canonical_bytes(self) -> bytes:
        """Deterministic encoding: sorted keys, no floats, explicit nulls, compact separators (E-1).

        The bytes cover the fact and its chain link, but **not** the id or the HMAC itself: a replay
        with a fresh id must not change the sealed bytes of an identical fact.
        """
        document = {
            "event_type": self.event_type,
            "payload": _normalise(self.payload),
            "subject": {
                "intent": self.subject_intent_id,
                "invoice": self.subject_invoice_id,
                "payee": self.subject_payee_id,
            },
            "constitution_version": self.constitution_version,
            "actor": self.actor,
            "occurred_at": self.occurred_at.isoformat(),
            "previous_hash": self.previous_hash,
        }
        return json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

    def hash(self) -> EnvelopeHash:
        """The value anchored on-chain: hash over `canonical_bytes()` plus the sealed HMAC (E-1)."""
        return EnvelopeHash.compute(self.canonical_bytes(), self.hmac)

    def hmac_is_valid(self, signer: EnvelopeSigner) -> bool:
        """Recompute the HMAC over the bytes as they are now and compare (E-2, E-7)."""
        return signer.verify(self.canonical_bytes(), self.hmac)

    def verify(self, signer: EnvelopeSigner, anchor: Anchor | None) -> Verification:
        """Re-verify this envelope against its HMAC and its anchor (E-6 … E-8).

        Returns:
            `Verification(VERIFIED, anchor_tx=…)` when both checks pass.
            `Verification(UNANCHORED)` when no anchor exists yet — not a tamper failure.

        Raises:
            HmacMismatch: the recomputed HMAC differs; `field` names the sealed field that failed.
            AnchorMismatch: the anchor belongs to a different envelope hash.
        """
        anchor_tx = anchor.anchor_tx if anchor is not None else ""
        if not self.hmac_is_valid(signer):
            raise HmacMismatch(failing_field="payload", anchor_tx=anchor_tx)
        if anchor is None:
            return Verification(result=VerificationResult.UNANCHORED)

        envelope_hash = self.hash()
        if not anchor.matches(envelope_hash):
            raise AnchorMismatch(
                envelope_hash=envelope_hash.value,
                anchor_hash=anchor.envelope_hash.value,
                anchor_tx=anchor.anchor_tx,
            )
        return Verification(result=VerificationResult.VERIFIED, anchor_tx=anchor.anchor_tx)

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
        return EvidenceEnvelope.from_event(
            event,
            signer=signer,
            actor=actor,
            previous_hash=self.hash().value,
            anchor_mode=anchor_mode,
        )

    @classmethod
    def with_id(cls, envelope_id: EnvelopeId | None = None) -> EnvelopeId:
        """Allocate an envelope identity (the uuid factory is the one non-stub exception, E-5)."""
        return envelope_id or EnvelopeId(new_id())
