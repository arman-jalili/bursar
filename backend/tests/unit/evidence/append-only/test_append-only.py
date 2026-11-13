"""E-5 — envelopes are append-only; a correction is a new envelope linked by `previous_hash`.

Canonical: docs/contracts/evidence-contract-freeze.md §1
Reference: .pi/architecture/decisions/ADR-002-data-storage-strategy.md

A rewritten row would leave the old hash anchored while the bytes behind it changed, which is exactly
the tampering the chain exists to expose. The repository port therefore has no `save`/`update`/`delete`;
the only correction path is an append whose `previous_hash` points at the original. Fails today from
`EvidenceEnvelope.corrected`.
"""

from __future__ import annotations

from src.authority.domain.events import PaymentAllowed

from tests.unit.evidence._fixtures import HmacSigner, an_envelope


class TestAppendOnly:
    def test_a_correction_is_a_new_envelope_linked_by_previous_hash(self) -> None:
        """E-5: the original id and chain link are untouched; the correction carries the old hash."""
        original = an_envelope()
        correction = original.corrected(
            PaymentAllowed(
                intent_id="intent-1", amount_micro_usdc=42_500_000, reservation_id="res-1"
            ),
            signer=HmacSigner("operator-held-test-key"),
            actor="authority",
        )

        assert correction.id != original.id
        assert correction.previous_hash == original.hash().value
        assert original.previous_hash is None
