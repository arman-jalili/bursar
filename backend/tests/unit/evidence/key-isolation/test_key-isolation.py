"""E-9 — the HMAC key never appears in an envelope payload, canonical bytes or sealed HMAC.

Canonical: docs/contracts/evidence-contract-freeze.md §1
Reference: .pi/architecture/decisions/ADR-005-authentication-authorization.md

The key is operator-held and must not be recoverable from anything Evidence stores, logs or returns.
The signer owns it; the envelope only receives the resulting HMAC. A test asserts the absence directly
rather than trusting a code review. Fails today from `EvidenceEnvelope.from_event`.
"""

from __future__ import annotations

from src.authority.domain.events import PaymentAllowed
from src.evidence.domain.evidence_envelope import EvidenceEnvelope

from tests.unit.evidence._fixtures import HmacSigner


class TestKeyIsolation:
    def test_the_hmac_key_never_appears_in_the_sealed_output(self) -> None:
        """E-9: neither the canonical bytes, the hmac nor the payload may contain the key."""
        secret = "operator-held-hmac-key-do-not-log"
        event = PaymentAllowed(
            intent_id="intent-1", amount_micro_usdc=42_500_000, reservation_id="res-1"
        )

        envelope = EvidenceEnvelope.from_event(event, signer=HmacSigner(secret), actor="authority")

        assert secret.encode() not in envelope.canonical_bytes()
        assert secret not in envelope.hmac
        assert secret not in str(dict(envelope.payload))
