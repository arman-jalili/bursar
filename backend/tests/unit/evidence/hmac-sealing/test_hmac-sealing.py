"""E-2 — every delivered event is sealed into exactly one envelope with a valid HMAC.

Canonical: docs/contracts/evidence-contract-freeze.md §1
Reference: .pi/architecture/modules/evidence.md#acceptance-criteria

ADR-003 delivers events from four publishers, at least once. The signer is the only thing that touches
the operator-held key, and the resulting HMAC must verify against the envelope's own canonical bytes.
Fails today from `EvidenceEnvelope.from_event`.
"""

from __future__ import annotations

import pytest
from src.authority.domain.events import PaymentAllowed, PaymentRefused
from src.billing.domain.events import InvoiceRecorded
from src.evidence.domain.evidence_envelope import EvidenceEnvelope
from src.mandate.domain.events import PayeeQuarantined

from tests.unit.evidence._fixtures import HmacSigner

EVENTS = [
    PaymentAllowed(intent_id="intent-1", amount_micro_usdc=42_500_000, reservation_id="res-1"),
    PaymentRefused(
        intent_id="intent-2",
        reason_codes=("cap_exceeded",),
        refused_at_iso="2026-11-13T12:00:00+00:00",
    ),
    InvoiceRecorded(
        invoice_id="invoice-1",
        payee_id="payee-1",
        invoice_hash="hash-1",
        amount_micro_usdc=42_500_000,
        due_date_iso="2026-12-01",
        presented_digest="digest-1",
    ),
    PayeeQuarantined(
        payee_id="payee-1",
        reason="bank_digest_mismatch",
        at_iso="2026-11-13T12:00:00+00:00",
    ),
]


class TestHmacSealing:
    @pytest.mark.parametrize("event", EVENTS)
    def test_every_delivered_event_is_sealed_with_a_verifiable_hmac(self, event) -> None:
        """E-2: one event → one envelope, and the HMAC recomputes over the sealed bytes."""
        signer = HmacSigner("operator-held-test-key")

        envelope = EvidenceEnvelope.from_event(event, signer=signer, actor="authority")

        assert envelope.hmac_is_valid(signer)
        assert envelope.event_type == event.event_name
