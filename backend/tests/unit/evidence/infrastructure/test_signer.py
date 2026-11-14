"""E-9/E-2 — the signer keeps the operator key inside itself and seals verifiably."""

from __future__ import annotations

import pytest
from src.evidence.domain.errors import SigningUnavailable
from src.evidence.infrastructure.anchor import ConfiguredAnchorPolicy
from src.evidence.infrastructure.signer import HmacSigner


class TestHmacSigner:
    def test_sign_and_verify_round_trip(self) -> None:
        signer = HmacSigner("operator-held-test-key")
        mac = signer.sign(b'{"a":1}')
        assert signer.verify(b'{"a":1}', mac) is True
        assert signer.verify(b'{"a":2}', mac) is False

    def test_an_empty_key_cannot_boot(self) -> None:
        with pytest.raises(SigningUnavailable):
            HmacSigner("")

    def test_repr_never_contains_the_key(self) -> None:
        signer = HmacSigner("operator-held-test-key")
        assert "operator-held-test-key" not in repr(signer)
        assert "<redacted>" in repr(signer)


class TestConfiguredAnchorPolicy:
    def test_default_and_per_event_modes(self) -> None:
        policy = ConfiguredAnchorPolicy(
            default="batched", per_event={"PaymentRefused": "per_envelope"}
        )
        assert policy.mode_for("PaymentAllowed") == "batched"
        assert policy.mode_for("PaymentRefused") == "per_envelope"
