"""E-8 — an envelope pointed at a different anchor hash raises `ANCHOR_MISMATCH`.

Canonical: docs/contracts/evidence-contract-freeze.md §1
Reference: .pi/architecture/modules/evidence.md#acceptance-criteria

The HMAC can be perfectly valid and the envelope still be lying about which on-chain record proves it.
The anchor comparison is the second, independent check: a locally consistent forgery cannot borrow
somebody else's anchor. Fails today from `EvidenceEnvelope.verify`.
"""

from __future__ import annotations

import pytest
from src.evidence.domain.errors import AnchorMismatch
from src.evidence.domain.values import EnvelopeHash

from tests.unit.evidence._fixtures import AcceptingSigner, an_anchor, an_envelope


class TestAnchorMismatch:
    def test_an_envelope_pointed_at_a_foreign_anchor_hash_is_refused(self) -> None:
        """E-8: a valid HMAC does not excuse a mismatched anchor hash."""
        envelope = an_envelope()
        foreign_anchor = an_anchor(EnvelopeHash("a-different-envelope-hash"))

        with pytest.raises(AnchorMismatch):
            envelope.verify(AcceptingSigner(), foreign_anchor)
