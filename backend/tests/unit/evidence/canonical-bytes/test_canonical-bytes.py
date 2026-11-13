"""E-1 — the same envelope content produces byte-identical canonical bytes.

Canonical: docs/contracts/evidence-contract-freeze.md §1
Reference: .pi/architecture/modules/evidence.md#acceptance-criteria

Verification is only meaningful if the bytes can be reproduced. A canonical encoder that respected
dict insertion order would make a re-serialised payload look like tampering, and a replayed event
could never be proved identical. Both tests fail today because `canonical_bytes` / `EnvelopeHash.compute`
raise `NotImplementedError`.
"""

from __future__ import annotations

from dataclasses import replace

from src.evidence.domain.values import EnvelopeHash

from tests.unit.evidence._fixtures import an_envelope


class TestCanonicalBytes:
    def test_key_order_does_not_change_the_sealed_bytes(self) -> None:
        """E-1: the same payload in a different key order must encode to the same bytes."""
        first = an_envelope(
            payload={"amount_micro_usdc": 42_500_000, "reason_codes": ["cap_exceeded"]}
        )
        second = replace(
            first,
            payload={"reason_codes": ["cap_exceeded"], "amount_micro_usdc": 42_500_000},
        )

        assert first.canonical_bytes() == second.canonical_bytes()

    def test_the_same_bytes_hash_the_same_twice(self) -> None:
        """E-1: `EnvelopeHash.compute` is deterministic — a drifting hash cannot be the anchor value."""
        first = EnvelopeHash.compute(b'{"amount_micro_usdc":42500000}', "hmac-1")
        second = EnvelopeHash.compute(b'{"amount_micro_usdc":42500000}', "hmac-1")

        assert first.value == second.value
