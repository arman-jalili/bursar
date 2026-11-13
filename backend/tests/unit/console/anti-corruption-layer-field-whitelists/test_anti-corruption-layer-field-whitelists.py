"""CON-01 — every surface owns its whitelist; there is no shared "pass everything" projection.

Canonical: .pi/architecture/modules/console.md#anti-corruption-layer--field-whitelists
Reference: docs/contracts/console-contract-freeze.md §1 (CON-01), §2.8

Six surfaces, six tuples. The failure this prevents is not only an unknown key: a single shared
tuple would let `typed_data_hash` reach the payer and the envelope payload reach the evidence list.
"""

from __future__ import annotations

import pytest
from src.console.application.errors import WhitelistViolation
from src.console.infrastructure.acl import (
    project_constitution,
    project_evidence,
    project_owner_inbox,
    project_payee,
    project_payer_bill,
    project_verification,
)


class TestAclWhitelists:
    def test_a_payee_payload_with_model_output_is_refused_not_forwarded(self) -> None:
        """CON-01: a key the whitelist cannot classify makes the projection fail, not guess."""
        with pytest.raises(WhitelistViolation):
            project_payee({"payee_id": "p-1", "display_name": "Northwind", "reasoning": "trusted"})

    def test_a_constitution_payload_is_narrowed_by_its_own_whitelist(self) -> None:
        """CON-01: cap and threshold come from Mandate verbatim; the console adds no derived field."""
        with pytest.raises(WhitelistViolation):
            project_constitution({"version": "c-7", "cap_usdc": "500.00", "internal_note": "x"})

    def test_a_verification_row_is_projected_by_the_verification_whitelist(self) -> None:
        """CON-01/CON-08: the verdict row is its own shape; it must not reuse the envelope whitelist."""
        projected = project_verification(
            {"envelope_id": "env-1", "outcome": "verified", "payload": {"secret": "x"}}
        )
        assert projected["outcome"] == "verified"
        assert "payload" not in projected

    def test_the_owner_inbox_and_payer_bill_have_different_audiences(self) -> None:
        """CON-01: one list for both screens would hand the payer the fields the owner signs."""
        payer_bill = project_payer_bill(
            {
                "invoice_id": "inv-1",
                "payee_name": "Northwind Insurance",
                "amount_usdc": "320.00",
                "status": "RECEIVED",
                "typed_data_hash": "0xhash",
                "bank_digest": "sha256:9f2ab7c1e0d4",
            }
        )
        assert "typed_data_hash" not in payer_bill
        assert "bank_digest" not in payer_bill

    def test_the_verification_surface_cannot_return_the_envelope_payload(self) -> None:
        """CON-01: the owner sees Evidence's verdict, not its payload (the envelope may hold PII)."""
        projected = project_verification(
            {"envelope_id": "env-1", "outcome": "verified", "payload": {"secret": "x"}}
        )
        assert "payload" not in projected

    def test_the_constitution_surface_does_not_forward_signing_material(self) -> None:
        """CON-01: the constitution is display-only; a key field would make the surface a write."""
        projected = project_constitution(
            {"version": "c-7", "cap_usdc": "500.00", "hmac_key": "k", "private_key": "p"}
        )
        assert "hmac_key" not in projected
        assert "private_key" not in projected

    def test_the_verification_fields_are_not_a_copy_of_the_envelope_fields(self) -> None:
        """CON-01: two surfaces that share a tuple drift into one audience."""
        envelope = project_evidence({"envelope_id": "env-1", "outcome": "tampered"})
        verification = project_verification({"envelope_id": "env-1", "outcome": "tampered"})
        assert "outcome" in verification
        assert "outcome" not in envelope

    def test_every_surface_projection_returns_at_least_one_field(self) -> None:
        """CON-01: an empty whitelist would silently blank a screen instead of failing review."""
        projected = (
            project_owner_inbox({"approval_id": "ap-1"}),
            project_payer_bill({"invoice_id": "inv-1"}),
            project_payee({"payee_id": "p-1"}),
            project_constitution({"version": "c-7"}),
            project_evidence({"envelope_id": "env-1"}),
            project_verification({"envelope_id": "env-1"}),
        )
        assert all(projected)
