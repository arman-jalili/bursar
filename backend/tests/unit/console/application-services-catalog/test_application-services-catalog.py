"""CON-02 / CON-05 / CON-06 / CON-08 — the three catalogued projections compose, never decide.

Canonical: .pi/architecture/modules/console.md#application-services-catalog
Reference: docs/contracts/console-contract-freeze.md §1, §2.7

The names are the contract the router, the React app and the tests refer to. Each test drives the
projection with upstream payloads and asserts what the screen would receive: exact owner fields,
household payer language, and Evidence's verdict passed through.
"""

from __future__ import annotations

from collections.abc import Mapping

from src.console.application.dto import BillStatus, VerificationOutcome
from src.console.application.services import (
    ProjectApprovalInbox,
    ProjectEvidence,
    ProjectPayerBills,
)

ADDRESS = "0x7A3fC2b1D4e5F60718293aBcDeF0123456789E9c2"
DIGEST = "sha256:9f2ab7c1e0d4"
PENDING = {
    "approval_id": "ap-1",
    "intent_id": "intent-1",
    "invoice_id": "inv-1",
    "payee_name": "Northwind Insurance",
    "payee_address": ADDRESS,
    "amount_usdc": "320.00",
    "bank_digest": DIGEST,
    "is_new_payee": True,
    "requires_owner_signature": True,
    "reason_codes": [],
    "expires_at": "2026-11-13T15:00:00Z",
    "typed_data_hash": "0xhash",
    "internal_note": "agent guess",
}
SETTLED_INVOICE = {
    "invoice_id": "inv-1",
    "payee_name": "Northwind Energy",
    "amount_usdc": "320.00",
    "status": "SETTLED",
    "payout_simulated": True,
    "internal_note": "operator note",
}
RECEIPT = {"invoice_id": "inv-1", "tx_hash": "0xabc123", "settled_at": "2026-11-13T14:02:00Z"}


class _Approvals:
    async def list_pending(self, owner_scope: str) -> tuple[Mapping[str, object], ...]:
        return (PENDING,)

    async def submit_signature(
        self, approval_id: str, raw_body: bytes, content_type: str
    ) -> Mapping[str, object]:
        return {"granted": True, "reason_codes": []}


class _Determinations:
    async def reasons_for(self, intent_id: str) -> tuple[str, ...]:
        return ()


class _Constitution:
    async def current(self) -> Mapping[str, object]:
        return {
            "version": "c-7",
            "cap_usdc": "500.00",
            "threshold_usdc": "100.00",
            "published_at": "2026-11-01T09:00:00Z",
        }

    async def payees(self) -> tuple[Mapping[str, object], ...]:
        return ({"payee_id": "p-1", "display_name": "Northwind", "status": "ACTIVE"},)


class _Bills:
    async def list_invoices(self, scope: str) -> tuple[Mapping[str, object], ...]:
        return (SETTLED_INVOICE,)

    async def get_invoice(self, invoice_id: str) -> Mapping[str, object]:
        return SETTLED_INVOICE


class _Receipts:
    async def receipt_for(self, invoice_id: str) -> Mapping[str, object] | None:
        return RECEIPT


class _Evidence:
    async def list_envelopes(self, intent_id: str | None) -> tuple[Mapping[str, object], ...]:
        return ({"envelope_id": "env-1", "event_type": "PaymentIntentIssued"},)

    async def verify(self, envelope_id: str) -> Mapping[str, object]:
        return {"envelope_id": envelope_id, "outcome": "tampered", "checked_at": "2026-11-13"}


class TestApplicationServicesCatalog:
    async def test_the_owner_inbox_projection_carries_the_exact_intent_fields(self) -> None:
        """CON-02: the inbox is Authority's fields, verbatim — no truncation, no model output."""
        items = await ProjectApprovalInbox(
            _Approvals(), _Determinations(), _Constitution()
        ).execute("owner-token")

        assert items[0].payee_address == ADDRESS
        assert items[0].bank_digest == DIGEST
        assert items[0].amount_usdc == "320.00"
        assert items[0].typed_data_hash == "0xhash"

    async def test_the_payer_bills_projection_speaks_household_language(self) -> None:
        """CON-05/CON-06: "Paid" plus the demo label, never a status enum or crypto term."""
        bills = await ProjectPayerBills(_Bills(), _Receipts()).execute("payer-token")

        assert bills[0].status is BillStatus.SETTLED
        assert bills[0].status_plain == "Paid"
        assert bills[0].payout_simulated is True
        assert bills[0].payout_label

    async def test_the_evidence_projection_proxies_the_verification_verdict(self) -> None:
        """CON-08: the third catalogued projection renders Evidence's verdict, it does not re-verify."""
        result = await ProjectEvidence(_Evidence()).verify("env-1")
        assert result.outcome is VerificationOutcome.TAMPERED

    async def test_the_owner_display_reads_ride_the_inbox_projection(self) -> None:
        """CON-01: payees and constitution are display-only reads; a fourth projection is ceremony."""
        inbox = ProjectApprovalInbox(_Approvals(), _Determinations(), _Constitution())

        payees = await inbox.payees("owner-token")
        version = await inbox.constitution_version("owner-token")

        assert payees[0].display_name == "Northwind"
        assert version.version == "c-7"
        assert version.cap_usdc == "500.00"
