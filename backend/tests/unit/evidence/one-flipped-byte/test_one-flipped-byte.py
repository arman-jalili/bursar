"""E-7 — one changed payload byte raises `HMAC_MISMATCH` and names the field.

Canonical: docs/contracts/evidence-contract-freeze.md §1
Reference: .pi/architecture/modules/evidence.md#acceptance-criteria

Scenario 7's tamper half. The HMAC is recomputed over the bytes as they are now; a single changed byte
must be enough to fail, and the failure must name the sealed field instead of returning a bare boolean.
The anchor is untouched — the point is that local tampering is detectable *and* independently provable
on-chain. Fails today from `EvidenceEnvelope.verify`.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from src.evidence.domain.errors import HmacMismatch
from src.evidence.domain.values import VerificationResult

from tests.unit.evidence._fixtures import RefusingSigner, an_anchor, an_envelope


class TestOneFlippedByte:
    def test_one_changed_payload_byte_is_named_as_a_hmac_mismatch(self) -> None:
        """E-7: the payload is the failing field and the anchor still points at the original hash."""
        original = an_envelope(payload={"amount_micro_usdc": 42_500_000})
        tampered = replace(original, payload={"amount_micro_usdc": 42_500_001})
        anchor = an_anchor(original.hash())

        with pytest.raises(HmacMismatch) as caught:
            tampered.verify(RefusingSigner(), anchor)

        assert caught.value.result is VerificationResult.HMAC_MISMATCH
        assert caught.value.details["field"] == "payload"
        assert caught.value.details["anchor_tx"] == anchor.anchor_tx
        assert anchor.envelope_hash.value == original.hash().value
