"""E-2 / E-3 — the envelope carries the fact's subject and chain link without reinterpreting it.

Canonical: docs/contracts/evidence-contract-freeze.md §1
Reference: .pi/architecture/modules/evidence.md#components-evidenceenvelope

An envelope is a wrapper, not an editor: the subject ids come from the publisher's payload, the actor
is recorded, and a freshly sealed envelope starts a chain (`previous_hash is None`). Fails today from
`EvidenceEnvelope.from_event`.
"""

from __future__ import annotations

from src.authority.domain.events import PaymentRefused
from src.evidence.domain.evidence_envelope import EvidenceEnvelope

from tests.unit.evidence._fixtures import HmacSigner


class TestEvidenceEnvelope:
    def test_a_fresh_envelope_records_the_subject_actor_and_no_previous_hash(self) -> None:
        """E-2: sealing is additive; the first envelope has no predecessor and keeps the fact's id."""
        event = PaymentRefused(
            intent_id="intent-42",
            reason_codes=("payee_quarantined",),
            refused_at_iso="2026-11-13T12:00:00+00:00",
        )

        envelope = EvidenceEnvelope.from_event(
            event, signer=HmacSigner("operator-held-test-key"), actor="authority"
        )

        assert envelope.subject_intent_id == "intent-42"
        assert envelope.actor == "authority"
        assert envelope.previous_hash is None
