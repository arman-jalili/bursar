"""E-6 — an untouched envelope verifies as `VERIFIED` with its anchor transaction.

Canonical: docs/contracts/evidence-contract-freeze.md §1
Reference: docs/architecture/modules/evidence.md#acceptance-criteria

Scenario 7's positive half. The envelope's HMAC still matches and the anchor records exactly the
envelope's hash, so the verifier returns the chain transaction that fixes the proof in time. Fails
today from `EvidenceEnvelope.hash` / `verify`.
"""

from __future__ import annotations

from src.evidence.domain.values import VerificationResult

from tests.unit.evidence._fixtures import AcceptingSigner, an_anchor, an_envelope


class TestVerifyOk:
    def test_an_untouched_envelope_verifies_with_its_anchor_tx(self) -> None:
        """E-6: HMAC valid + anchor hash equal → VERIFIED and the anchor transaction is returned."""
        envelope = an_envelope()
        anchor = an_anchor(envelope.hash())

        verification = envelope.verify(AcceptingSigner(), anchor)

        assert verification.result is VerificationResult.VERIFIED
        assert verification.anchor_tx == anchor.anchor_tx
