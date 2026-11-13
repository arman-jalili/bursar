"""CON-02 — `payee_address` and `bank_digest` reach the owner byte-identically to Authority's intent.

Canonical: .pi/architecture/modules/console.md#entity-relationship--projections-only-no-aggregates
Reference: docs/contracts/console-contract-freeze.md §1 (CON-02), §2.1

The signature binds these exact bytes. A formatter that truncates the address, lowercases a checksum
or re-derives the digest makes the screen disagree with what the owner signed — the failure scenario 5
(negative) exists to catch, moved one layer earlier where it is cheaper to see.
"""

from __future__ import annotations

from datetime import datetime

from src.console.application.dto import ApprovalInboxItem
from src.console.infrastructure.acl import OWNER_INBOX_FIELDS, project_owner_inbox

#: Mixed case is the checksum. Lowercasing this string changes the value, not the presentation.
ADDRESS = "0x7A3fC2b1D4e5F60718293aBcDeF0123456789E9c2"
DIGEST = "sha256:9f2ab7c1e0d4"


class TestExactFields:
    def test_the_projection_keeps_the_address_byte_identical(self) -> None:
        """CON-02: copy, never normalise — a checksum-case change is a different string."""
        projected = project_owner_inbox({"payee_address": ADDRESS, "bank_digest": DIGEST})
        assert projected["payee_address"] == ADDRESS
        assert projected["payee_address"] != ADDRESS.lower()

    def test_the_projection_keeps_the_digest_byte_identical(self) -> None:
        """CON-02: re-checksumming the digest would show a value the signature does not bind."""
        projected = project_owner_inbox({"payee_address": ADDRESS, "bank_digest": DIGEST})
        assert projected["bank_digest"] == DIGEST

    def test_an_amount_is_carried_as_the_exact_decimal_string(self) -> None:
        """CON-02: a float round-trip turns 320.00 into 319.99999999999994 before the owner sees it."""
        item = ApprovalInboxItem(
            approval_id="ap-1",
            intent_id="intent-1",
            invoice_id="inv-1",
            payee_name="Northwind Insurance",
            payee_address=ADDRESS,
            amount_usdc="320.00",
            bank_digest=DIGEST,
            is_new_payee=True,
            requires_owner_signature=True,
            reason_codes=(),
            expires_at=datetime(2026, 11, 13, 15, 0),
            typed_data_hash="0xhash",
        )
        assert item.amount_usdc == "320.00"
        assert str(float(item.amount_usdc)) != item.amount_usdc

    def test_the_owner_surface_keeps_both_bound_fields_on_the_whitelist(self) -> None:
        """CON-02: dropping either field would force the UI to re-derive it from another source."""
        assert "payee_address" in OWNER_INBOX_FIELDS
        assert "bank_digest" in OWNER_INBOX_FIELDS
