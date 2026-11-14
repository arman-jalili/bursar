"""Canonical-encoding edge cases and the identity factory (E-1, E-5).

Canonical: docs/contracts/evidence-contract-freeze.md §2.2
Reference: docs/architecture/modules/evidence.md#components-evidenceenvelope
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

import pytest
from src.authority.domain.events import PaymentAllowed
from src.evidence.domain.evidence_envelope import EvidenceEnvelope
from src.evidence.domain.ids import EnvelopeId

from tests.unit.evidence._fixtures import HmacSigner, an_envelope


class Colour(enum.StrEnum):
    RED = "red"


class TestCanonicalEncodingEdges:
    def test_floats_are_refused(self) -> None:
        with pytest.raises(ValueError, match="floats"):
            an_envelope(payload={"amount": 1.5}).canonical_bytes()

    def test_dates_enums_decimals_and_sets_are_normalised(self) -> None:
        envelope = an_envelope(
            payload={
                "day": date(2026, 11, 13),
                "colour": Colour.RED,
                "fee": Decimal("1.25"),
                "codes": {"b", "a"},
            }
        )
        text = envelope.canonical_bytes().decode()
        assert '"day":"2026-11-13"' in text
        assert '"colour":"red"' in text
        assert '"fee":"1.25"' in text
        assert '"codes":["a","b"]' in text

    def test_a_naive_occurred_at_is_refused(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            EvidenceEnvelope.from_event(
                PaymentAllowed(
                    intent_id="intent-1",
                    amount_micro_usdc=1,
                    reservation_id="res-1",
                    occurred_at=datetime(2026, 11, 13, 12, 0),
                ),
                signer=HmacSigner("operator-held-test-key"),
                actor="authority",
            )

    def test_with_id_accepts_a_given_identity(self) -> None:
        chosen = EnvelopeId("env-chosen")
        assert EvidenceEnvelope.with_id(chosen) == chosen

    def test_the_id_is_not_part_of_the_sealed_bytes(self) -> None:
        first = an_envelope()
        second = an_envelope(id=EnvelopeId("different-id"))
        assert first.canonical_bytes() == second.canonical_bytes()

    def test_the_hmac_is_not_part_of_the_sealed_bytes(self) -> None:
        first = an_envelope(hmac="a")
        second = an_envelope(hmac="b")
        assert first.canonical_bytes() == second.canonical_bytes()
        assert first.hash() != second.hash()

    def test_empty_hash_input_is_refused(self) -> None:
        from src.evidence.domain.values import EnvelopeHash

        with pytest.raises(ValueError):
            EnvelopeHash("")
