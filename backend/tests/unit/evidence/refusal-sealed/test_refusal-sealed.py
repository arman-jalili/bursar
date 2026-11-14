"""E-3 — a denied payment is sealed as `PaymentRefused` carrying its reason codes.

Canonical: docs/contracts/evidence-contract-freeze.md §1
Reference: .pi/architecture/modules/evidence.md#acceptance-criteria

Scenarios 2, 3 and 4 all end in a refusal, and a refusal is the same shape of record as a settlement —
not a lesser one. If the reason codes were dropped, the console could not explain the refusal and the
auditor could not assert on it. Fails today from `EvidenceEnvelope.from_event`.
"""

from __future__ import annotations

from src.authority.domain.events import PaymentRefused
from src.evidence.domain.evidence_envelope import EvidenceEnvelope

from tests.unit.evidence._fixtures import HmacSigner


class TestRefusalSealed:
    def test_a_denied_payment_is_sealed_with_its_reason_codes(self) -> None:
        """E-3: event_type is `PaymentRefused`, the intent is the subject, and every code survives."""
        event = PaymentRefused(
            intent_id="intent-9",
            reason_codes=("cap_exceeded", "payee_frozen"),
            refused_at_iso="2026-11-13T12:00:00+00:00",
        )

        envelope = EvidenceEnvelope.from_event(
            event, signer=HmacSigner("operator-held-test-key"), actor="authority"
        )

        assert envelope.event_type == "PaymentRefused"
        assert envelope.subject_intent_id == "intent-9"
        assert tuple(envelope.payload["reason_codes"]) == ("cap_exceeded", "payee_frozen")
