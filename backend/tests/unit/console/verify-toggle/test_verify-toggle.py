"""CON-08 — the evidence view proxies Evidence's verdict: verified, then tampered after one byte.

Canonical: docs/architecture/modules/console.md#key-use-case-sequence--owner-approves-on-a-phone
Reference: docs/contracts/console-contract-freeze.md §1 (CON-08), §2.5, §2.9

Scenario 7 flips a byte in a sealed envelope. The console must show Evidence's `tampered`, not its
own opinion: a second verifier would be a weaker witness that can disagree with the anchor.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from src.console.application.dto import VerificationOutcome
from src.console.application.errors import VerificationRefused
from src.console.application.services import ProjectEvidence
from src.console.infrastructure.acl import project_verification
from src.console.infrastructure.http import EvidenceHttpAdapter, HttpAdapterConfig

CONFIG = HttpAdapterConfig(base_url="http://evidence.test")


class _Evidence:
    """Returns the verdict Evidence would return; it never inspects the envelope."""

    def __init__(self, outcome: str) -> None:
        self._outcome = outcome

    async def list_envelopes(self, intent_id: str | None) -> tuple[Mapping[str, object], ...]:
        return ()

    async def verify(self, envelope_id: str) -> Mapping[str, object]:
        return {"envelope_id": envelope_id, "outcome": self._outcome, "checked_at": "2026-11-13"}


class TestVerifyToggle:
    async def test_an_untouched_envelope_reads_verified(self) -> None:
        """CON-08: the console renders Evidence's verdict, so a clean envelope says verified."""
        result = await ProjectEvidence(_Evidence("verified")).verify("env-untouched")
        assert result.outcome is VerificationOutcome.VERIFIED

    async def test_a_tampered_envelope_reads_tampered(self) -> None:
        """CON-08: scenario 7 — one flipped byte must flip the label, not be rounded to "verified"."""
        result = await ProjectEvidence(_Evidence("tampered")).verify("env-tampered")
        assert result.outcome is VerificationOutcome.TAMPERED

    async def test_an_unrecognised_verdict_is_refused_not_defaulted(self) -> None:
        """CON-08: an unknown answer must not be rendered as verified or as a truthy default."""
        with pytest.raises(VerificationRefused):
            await ProjectEvidence(_Evidence("maybe")).verify("env-1")

    def test_the_projection_keeps_the_verdict_distinct_from_the_envelope(self) -> None:
        """CON-08: the toggle renders `outcome`; reusing the envelope shape would lose it."""
        projected = project_verification(
            {"envelope_id": "env-tampered", "outcome": "tampered", "payload": {"x": 1}}
        )
        assert projected["outcome"] == "tampered"
        assert "payload" not in projected

    async def test_the_adapter_transports_the_verdict_without_computing_one(self) -> None:
        """CON-08: the adapter's job is transport; the verdict is Evidence's answer verbatim."""
        verdict = await EvidenceHttpAdapter(CONFIG).verify("env-untouched")
        assert verdict["outcome"] == "verified"
