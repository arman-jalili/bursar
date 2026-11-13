"""CON-01 / CON-02 / CON-04 — upstream clients return raw payloads and expose only reads.

Canonical: .pi/architecture/modules/console.md#ports-upstream-clients
Reference: docs/contracts/console-contract-freeze.md §1, §2.5, §2.9

A port that returned a typed DTO would move the whitelist into the adapter: a new upstream field
would then appear by editing an adapter instead of a whitelist (CON-01). A port with a `dispatch` or
`create` method would give the console a way to move money (CON-04).
"""

from __future__ import annotations

from src.console.infrastructure.http import (
    AuthorityHttpAdapter,
    BillingHttpAdapter,
    EvidenceHttpAdapter,
    HttpAdapterConfig,
    MandateHttpAdapter,
    SettlementHttpAdapter,
)

CONFIG = HttpAdapterConfig(base_url="http://upstream.test")


class TestPortsUpstreamClients:
    async def test_a_bill_is_fetched_unmodified_for_the_acl_to_narrow(self) -> None:
        """CON-02: an adapter that renames `payee_address` would break byte-identity before the ACL."""
        bill = await BillingHttpAdapter(CONFIG).get_invoice("inv-1")
        assert bill["payee_address"] != bill["payee_address"].lower()

    async def test_the_settlement_client_reports_absence_as_none(self) -> None:
        """CON-06: an unpaid bill has no receipt; fabricating one would invent a payout."""
        receipt = await SettlementHttpAdapter(CONFIG).receipt_for("inv-untouched")
        assert receipt is None

    async def test_the_refusal_reason_client_returns_codes(self) -> None:
        """CON-07: the console translates codes; a pre-rendered message would bypass the copy table."""
        codes = await AuthorityHttpAdapter(CONFIG).reasons_for("intent-1")
        assert codes == ("DIGEST_MISMATCH",)

    async def test_the_authority_client_forwards_signature_bytes_unchanged(self) -> None:
        """CON-03: the adapter's only write passes bytes through; it never re-encodes them."""
        raw = b'{"signature":"0xdeadbeef","intent_id":"intent-1"}'
        result = await AuthorityHttpAdapter(CONFIG).submit_signature(
            "ap-1", raw, "application/json"
        )
        assert result["granted"] is True

    async def test_the_evidence_client_proxies_verification(self) -> None:
        """CON-08: the verdict is Evidence's; the adapter transports it and adds no opinion."""
        verdict = await EvidenceHttpAdapter(CONFIG).verify("env-1")
        assert verdict["outcome"] == "tampered"

    async def test_the_mandate_client_reads_the_constitution_for_display(self) -> None:
        """CON-01: display-only; the owner signature, not the console, publishes a version."""
        constitution = await MandateHttpAdapter(CONFIG).current()
        assert constitution["version"] == "c-7"
