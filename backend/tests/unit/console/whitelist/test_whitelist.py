"""CON-01 — a field the whitelist does not name never reaches a console surface.

Canonical: docs/architecture/modules/console.md#anti-corruption-layer--field-whitelists
Reference: docs/contracts/console-contract-freeze.md §1 (CON-01), §2.8

Authority may add `internal_note` at any time; only an explicit whitelist edit may make it visible.
The projection is asserted here, not the display component: if the leak cannot leave the ACL, no
later formatting change can re-introduce it.
"""

from __future__ import annotations

import pytest
from src.console.application.errors import WhitelistViolation
from src.console.infrastructure.acl import project_owner_inbox, project_payer_bill

UPSTREAM_WITH_MODEL_OUTPUT = {
    "approval_id": "ap-1",
    "intent_id": "intent-1",
    "payee_name": "Northwind Insurance",
    "amount_usdc": "320.00",
    "internal_note": "agent guess: this looks fine",
}


class TestWhitelist:
    def test_model_output_cannot_reach_the_owner_inbox(self) -> None:
        """CON-01: `internal_note` is model output; a projection that forwards it makes it a fact."""
        with pytest.raises(WhitelistViolation):
            project_owner_inbox(UPSTREAM_WITH_MODEL_OUTPUT)

    def test_model_output_cannot_reach_a_payer_bill(self) -> None:
        """CON-01: the payer surface is the one a household reads; model output there is advice."""
        with pytest.raises(WhitelistViolation):
            project_payer_bill({**UPSTREAM_WITH_MODEL_OUTPUT, "invoice_id": "inv-1"})

    def test_a_benign_unknown_key_is_dropped_rather_than_forwarded(self) -> None:
        """CON-01: the default is drop — an un-named key is not evidence and must not be copied."""
        projected = project_owner_inbox({"approval_id": "ap-1", "debug_trace": {"hop": 2}})
        assert "debug_trace" not in projected
        assert projected["approval_id"] == "ap-1"

    def test_every_forbidden_upstream_key_is_refused_by_the_owner_projection(self) -> None:
        """CON-01: each name that looks like model output is a refusal, not a silent drop."""
        for forbidden in ("internal_note", "raw_payload", "confidence", "agent_guess", "reasoning"):
            with pytest.raises(WhitelistViolation):
                project_owner_inbox({"approval_id": "ap-1", forbidden: "model output"})

    def test_the_payer_whitelist_keeps_audience_fields_out(self) -> None:
        """CON-01: a payer is not the signer, so the signed fields are not theirs to see."""
        projected = project_payer_bill(
            {
                "invoice_id": "inv-1",
                "typed_data_hash": "0xhash",
                "bank_digest": "sha256:9f2ab7c1e0d4",
            }
        )
        assert "typed_data_hash" not in projected
        assert "bank_digest" not in projected
