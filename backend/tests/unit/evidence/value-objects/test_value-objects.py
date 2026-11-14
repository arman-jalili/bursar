"""E-1 — the envelope hash changes when a sealed input changes.

Canonical: docs/contracts/evidence-contract-freeze.md §1
Reference: docs/architecture/modules/evidence.md#components

The hash is the value anchored on-chain. If one changed byte produced the same hash, the anchor would
prove the wrong fact; if unrelated calls produced different hashes for the same bytes, verification
would fail on untouched evidence. Fails today from `EnvelopeHash.compute`.
"""

from __future__ import annotations

from src.evidence.domain.values import EnvelopeHash


class TestEnvelopeHash:
    def test_one_changed_input_byte_changes_the_hash(self) -> None:
        """E-1: hashing is sensitive to every sealed byte, which is what makes tampering provable."""
        original = EnvelopeHash.compute(b'{"amount_micro_usdc":42500000}', "hmac-1")
        changed = EnvelopeHash.compute(b'{"amount_micro_usdc":42500001}', "hmac-1")

        assert original.value != changed.value
