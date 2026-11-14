"""Phase-B support surfaces: cache, copy tables, coercion and adapter transport.

Canonical: docs/architecture/modules/console.md#components
Reference: docs/contracts/console-contract-freeze.md §2.2, §2.6, §2.9, §2.10

The invariant suites prove the rules. This file proves the machinery that carries them: the TTL
cache stores projections only, the copy tables fail closed on unknown input, coercions refuse to
normalise a bound field (CON-02), and each adapter transports an upstream shape without editing it.
"""

from __future__ import annotations

import pytest
from src.console.application.dto import BillStatus, VerificationOutcome
from src.console.application.errors import (
    FieldFidelityViolation,
    PayerVocabularyViolation,
    RefusalReasonMissing,
    UnknownReasonCode,
    VerificationRefused,
    ViewportContractViolation,
)
from src.console.application.presentation import (
    Viewport,
    assert_mobile_contract,
    payee_status_copy,
    payer_status_copy,
    payout_label,
)
from src.console.application.refusals import DenialReasonCode, refusal_copy
from src.console.application.services import (
    ProjectApprovalInbox,
    ProjectEvidence,
    ProjectPayerBills,
)
from src.console.infrastructure.http import (
    AuthorityHttpAdapter,
    BillingHttpAdapter,
    EvidenceHttpAdapter,
    HttpAdapterConfig,
    MandateHttpAdapter,
    SettlementHttpAdapter,
)
from src.console.infrastructure.purity import declared_layers
from src.console.infrastructure.repository.memory_cache import InMemoryReadModelCache

CONFIG = HttpAdapterConfig(base_url="http://upstream.test")


class TestReadModelCache:
    def test_get_put_expiry_and_invalidate(self) -> None:
        """CON-02: TTL is the only expiry rule; invalidate handles one stale view."""
        now = [0.0]
        cache = InMemoryReadModelCache(clock=lambda: now[0])

        assert cache.get("missing") is None
        cache.put("bill:inv-1", {"invoice_id": "inv-1"}, ttl_seconds=5)
        assert cache.get("bill:inv-1") == {"invoice_id": "inv-1"}

        now[0] = 5.0
        assert cache.get("bill:inv-1") is None

        cache.put("bill:inv-1", {"invoice_id": "inv-1"}, ttl_seconds=5)
        cache.invalidate("bill:inv-1")
        assert cache.get("bill:inv-1") is None
        cache.invalidate("never-cached")

    def test_a_stored_projection_cannot_be_mutated_by_its_caller(self) -> None:
        """CON-01/CON-02: a cached view is immutable — mutating the input cannot rewrite the screen."""
        cache = InMemoryReadModelCache()
        value = {"invoice_id": "inv-1"}
        cache.put("k", value, ttl_seconds=60)
        value["internal_note"] = "leak"

        cached = cache.get("k")
        assert cached == {"invoice_id": "inv-1"}
        with pytest.raises(TypeError):
            cached["invoice_id"] = "other"  # type: ignore[index]

    def test_a_non_positive_ttl_is_a_programming_error(self) -> None:
        with pytest.raises(ValueError):
            InMemoryReadModelCache().put("k", {}, ttl_seconds=0)


class TestCopyTables:
    def test_an_unknown_status_cannot_be_rendered(self) -> None:
        """CON-05: an enum with no copy would print a raw upstream string."""
        with pytest.raises(PayerVocabularyViolation):
            payer_status_copy("PAID", payout_simulated=False)  # type: ignore[arg-type]

    def test_payee_copy_covers_known_and_unknown_statuses(self) -> None:
        assert payee_status_copy("ACTIVE") == "Active"
        assert payee_status_copy("SOMETHING_NEW") == "Under review"

    def test_a_non_simulated_payout_has_no_label(self) -> None:
        assert payout_label(False) == ""
        assert "simulated" in payout_label(True)

    def test_a_too_short_phone_fails_the_height_budget(self) -> None:
        with pytest.raises(ViewportContractViolation):
            assert_mobile_contract(Viewport(width_px=390, height_px=700))

    def test_a_taller_phone_passes(self) -> None:
        assert assert_mobile_contract(Viewport(width_px=430, height_px=932)) is None


class TestRefusalCopy:
    def test_an_unknown_code_is_refused_instead_of_printed(self) -> None:
        """CON-07: `DIGEST_MISMATCH` on a household screen is the raw code with extra steps."""
        with pytest.raises(UnknownReasonCode):
            refusal_copy(("NOT_A_REAL_CODE",))

    def test_multiple_codes_render_in_authority_order_without_duplicates(self) -> None:
        text = refusal_copy(
            (
                DenialReasonCode.DIGEST_MISMATCH,
                DenialReasonCode.PAYEE_FROZEN,
                DenialReasonCode.DIGEST_MISMATCH,
            )
        )
        assert text.index("bank details") < text.index("owner")
        assert text.count("Blocked") == 1


class TestPurity:
    def test_the_console_declares_exactly_three_layers(self) -> None:
        assert declared_layers() == ("application", "infrastructure", "interfaces")


class _Approvals:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    async def list_pending(self, owner_scope: str) -> tuple[dict[str, object], ...]:
        return (self.payload,)

    async def submit_signature(
        self, approval_id: str, raw_body: bytes, content_type: str
    ) -> dict[str, object]:
        return self.payload


class _NoDeterminations:
    async def reasons_for(self, intent_id: str) -> tuple[str, ...]:
        return ()


class _Constitution:
    async def current(self) -> dict[str, object]:
        return _CONSTITUTION

    async def payees(self) -> tuple[dict[str, object], ...]:
        return _PAYEES


class _Bills:
    def __init__(self, invoice: dict[str, object]) -> None:
        self.invoice = invoice

    async def list_invoices(self, scope: str) -> tuple[dict[str, object], ...]:
        return (self.invoice,)

    async def get_invoice(self, invoice_id: str) -> dict[str, object]:
        return self.invoice


class _NoReceipts:
    async def receipt_for(self, invoice_id: str) -> None:
        return None


class _Evidence:
    def __init__(self, verdict: dict[str, object] | None = None) -> None:
        self.verdict = verdict or {}

    async def list_envelopes(self, intent_id: str | None) -> tuple[dict[str, object], ...]:
        return (_ENVELOPE,)

    async def verify(self, envelope_id: str) -> dict[str, object]:
        return self.verdict


_PENDING = {
    "approval_id": "ap-1",
    "intent_id": "intent-1",
    "invoice_id": "inv-1",
    "payee_name": "Northwind Insurance",
    "payee_address": "0x7A3fC2b1D4e5F60718293aBcDeF0123456789E9c2",
    "amount_usdc": "320.00",
    "bank_digest": "sha256:9f2ab7c1e0d4",
    "is_new_payee": True,
    "requires_owner_signature": True,
    "reason_codes": ["DIGEST_MISMATCH"],
    "expires_at": "2026-11-13T15:00:00Z",
    "typed_data_hash": "0xhash",
}
_CONSTITUTION = {
    "version": "c-7",
    "cap_usdc": "500.00",
    "threshold_usdc": "100.00",
    "published_at": "2026-11-01T09:00:00Z",
}
_PAYEES = ({"payee_id": "p-1", "display_name": "Northwind", "status": "ACTIVE"},)
_ENVELOPE = {
    "envelope_id": "env-1",
    "event_type": "PaymentIntentIssued",
    "occurred_at": "2026-11-13T13:55:00Z",
    "result": "SEALED",
    "anchor_tx": "0xanchor1",
}


class TestOwnerProjectionEdges:
    async def test_payees_and_constitution_are_built_from_their_whitelists(self) -> None:
        inbox = ProjectApprovalInbox(_Approvals(_PENDING), _NoDeterminations(), _Constitution())

        payees = await inbox.payees("owner-token")
        current = await inbox.constitution_version("owner-token")

        assert payees[0].status_plain == "Active"
        assert current.cap_usdc == "500.00"

    async def test_an_unknown_reason_code_fails_the_projection(self) -> None:
        """CON-07: a code outside Authority's set cannot be translated, so it is refused."""
        pending = {**_PENDING, "reason_codes": ["NOT_A_REAL_CODE"]}
        inbox = ProjectApprovalInbox(_Approvals(pending), _NoDeterminations(), _Constitution())

        with pytest.raises(UnknownReasonCode):
            await inbox.execute("owner-token")

    async def test_a_missing_bound_field_is_a_fidelity_violation(self) -> None:
        """CON-02: the console cannot invent or shorten a field the signature binds."""
        pending = {key: value for key, value in _PENDING.items() if key != "payee_address"}
        inbox = ProjectApprovalInbox(_Approvals(pending), _NoDeterminations(), _Constitution())

        with pytest.raises(FieldFidelityViolation):
            await inbox.execute("owner-token")

    async def test_a_non_boolean_flag_is_refused(self) -> None:
        pending = {**_PENDING, "is_new_payee": "yes"}
        inbox = ProjectApprovalInbox(_Approvals(pending), _NoDeterminations(), _Constitution())

        with pytest.raises(FieldFidelityViolation):
            await inbox.execute("owner-token")

    async def test_a_bad_timestamp_is_refused(self) -> None:
        pending = {**_PENDING, "expires_at": "next tuesday"}
        inbox = ProjectApprovalInbox(_Approvals(pending), _NoDeterminations(), _Constitution())

        with pytest.raises(FieldFidelityViolation):
            await inbox.execute("owner-token")

    async def test_a_refusal_is_translated_for_the_owner(self) -> None:
        inbox = ProjectApprovalInbox(
            _Approvals({"granted": False, "reason_codes": ["DIGEST_MISMATCH"]}),
            _NoDeterminations(),
            _Constitution(),
        )

        outcome = await inbox.submit(
            "ap-1", raw_body=b"{}", content_type="application/json", owner_scope="owner"
        )

        assert outcome.granted is False
        assert outcome.reason_plain and "bank details" in outcome.reason_plain

    async def test_a_refusal_with_no_code_cannot_be_rendered(self) -> None:
        inbox = ProjectApprovalInbox(
            _Approvals({"granted": False, "reason_codes": []}),
            _NoDeterminations(),
            _Constitution(),
        )

        with pytest.raises(RefusalReasonMissing):
            await inbox.submit(
                "ap-1", raw_body=b"{}", content_type="application/json", owner_scope="owner"
            )


class TestPayerProjectionEdges:
    async def test_one_bill_uses_the_detail_screen_path(self) -> None:
        bill = await ProjectPayerBills(
            _Bills(
                {
                    "invoice_id": "inv-2",
                    "payee_name": "Water",
                    "amount_usdc": "48.50",
                    "status": "RECEIVED",
                    "payout_simulated": False,
                }
            ),
            _NoReceipts(),
        ).one("payer-token", "inv-2")

        assert bill.status is BillStatus.RECEIVED
        assert bill.status_plain == "Bill received"
        assert bill.payout_label is None

    async def test_a_refused_bill_carries_a_household_reason(self) -> None:
        """CON-07: a blocked payment is explained, never rendered with the raw code."""
        bill = await ProjectPayerBills(
            _Bills(
                {
                    "invoice_id": "inv-3",
                    "payee_name": "Water",
                    "amount_usdc": "48.50",
                    "status": "REFUSED",
                    "payout_simulated": False,
                    "reason_codes": ["DIGEST_MISMATCH"],
                }
            ),
            _NoReceipts(),
        ).one("payer-token", "inv-3")

        assert bill.refusal_reason and "bank details" in bill.refusal_reason
        assert "DIGEST_MISMATCH" not in bill.refusal_reason

    async def test_an_unknown_bill_status_is_refused(self) -> None:
        with pytest.raises(FieldFidelityViolation):
            await ProjectPayerBills(
                _Bills(
                    {
                        "invoice_id": "inv-4",
                        "payee_name": "Water",
                        "amount_usdc": "48.50",
                        "status": "TELEPORTED",
                        "payout_simulated": False,
                    }
                ),
                _NoReceipts(),
            ).one("payer-token", "inv-4")


class TestEvidenceProjectionEdges:
    async def test_envelope_list_carries_hashes_not_payloads(self) -> None:
        envelopes = await ProjectEvidence(_Evidence()).envelopes(None)

        assert envelopes[0].envelope_id == "env-1"
        assert envelopes[0].anchor_tx == "0xanchor1"

    async def test_an_unknown_verdict_is_refused(self) -> None:
        with pytest.raises(VerificationRefused):
            await ProjectEvidence(_Evidence({"envelope_id": "env-1", "outcome": "maybe"})).verify(
                "env-1"
            )

    async def test_a_verdict_without_a_timestamp_gets_the_check_time(self) -> None:
        result = await ProjectEvidence(
            _Evidence({"envelope_id": "env-1", "outcome": "verified"})
        ).verify("env-1")

        assert result.outcome is VerificationOutcome.VERIFIED


class TestUpstreamAdapters:
    async def test_authority_lists_pending_approvals(self) -> None:
        pending = await AuthorityHttpAdapter(CONFIG).list_pending("owner-token")
        assert pending and "payee_address" in pending[0]

    async def test_authority_refuses_a_parsed_signature_body(self) -> None:
        """CON-03: a parsed body has already been rewritten, so the adapter refuses it."""
        with pytest.raises(Exception, match="raw bytes"):
            await AuthorityHttpAdapter(CONFIG).submit_signature(
                "ap-1",
                "{}",
                "application/json",  # type: ignore[arg-type]
            )

    async def test_billing_lists_invoices_and_reads_one(self) -> None:
        adapter = BillingHttpAdapter(CONFIG)
        invoices = await adapter.list_invoices("payer-token")
        one = await adapter.get_invoice("inv-2")

        assert len(invoices) == 2
        assert one["invoice_id"] == "inv-2"

    async def test_settlement_returns_the_recorded_receipt(self) -> None:
        receipt = await SettlementHttpAdapter(CONFIG).receipt_for("inv-1")
        assert receipt is not None and receipt["tx_hash"] == "0xabc123"

    async def test_evidence_lists_envelopes_and_proxies_a_verdict(self) -> None:
        adapter = EvidenceHttpAdapter(CONFIG)
        envelopes = await adapter.list_envelopes("intent-1")
        verdict = await adapter.verify("env-untouched")

        assert envelopes[0]["envelope_id"] == "env-1"
        assert verdict["outcome"] == "verified"

    async def test_mandate_reads_payees_for_display(self) -> None:
        payees = await MandateHttpAdapter(CONFIG).payees()
        assert payees[0]["display_name"] == "Northwind Insurance"
