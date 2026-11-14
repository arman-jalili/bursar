"""The three Evidence events are frozen wire schemas (E-2, E-8).

Canonical: docs/contracts/evidence-contract-freeze.md §2.8
Reference: .pi/architecture/modules/evidence.md#domain-events
"""

from __future__ import annotations

from src.evidence.domain.events import (
    EnvelopeAnchored,
    EnvelopeSealed,
    EvidenceVerificationFailed,
)


class TestEvidenceEvents:
    def test_the_catalogue_is_exactly_three_events(self) -> None:
        assert EnvelopeSealed.event_name == "EnvelopeSealed"
        assert EnvelopeAnchored.event_name == "EnvelopeAnchored"
        assert EvidenceVerificationFailed.event_name == "EvidenceVerificationFailed"

    def test_envelope_sealed_carries_the_subject_and_hash(self) -> None:
        event = EnvelopeSealed(
            envelope_id="env-1",
            event_type="PaymentAllowed",
            subject_intent_id="intent-1",
            envelope_hash="hash-1",
            anchor_mode="per_envelope",
        )
        payload = event.to_payload()
        assert payload["envelope_id"] == "env-1"
        assert payload["event_type"] == "PaymentAllowed"
        assert payload["subject_intent_id"] == "intent-1"
        assert payload["envelope_hash"] == "hash-1"
        assert payload["anchor_mode"] == "per_envelope"

    def test_envelope_anchored_carries_the_chain_proof(self) -> None:
        event = EnvelopeAnchored(
            envelope_id="env-1",
            envelope_hash="hash-1",
            anchor_tx="0xanchor",
            block_number=19_000_000,
            chain_id=31337,
        )
        payload = event.to_payload()
        assert payload["anchor_tx"] == "0xanchor"
        assert payload["block_number"] == 19_000_000
        assert payload["chain_id"] == 31337

    def test_verification_failed_names_the_result_and_field(self) -> None:
        event = EvidenceVerificationFailed(
            envelope_id="env-1", result="HMAC_MISMATCH", failing_field="payload"
        )
        payload = event.to_payload()
        assert payload["result"] == "HMAC_MISMATCH"
        assert payload["failing_field"] == "payload"
