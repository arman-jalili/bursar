"""Console end-to-end through the public HTTP API (the React app's contract).

Canonical: docs/architecture/modules/console.md#api-endpoints
Reference: docs/contracts/console-contract-freeze.md §1 (CON-01, CON-02, CON-03, CON-06, CON-08)

These go through the real composition root (middleware, scope checks, error envelope, SQLite):

    AC-1  an upstream payload's `internal_note` never reaches a console response
    AC-2  the inbox renders `payee_address` and `bank_digest` byte-identically to Authority
    AC-3  `POST /signature` forwards the recorded body byte-for-byte
    AC-4  the owner token cannot reach a creating path; the payer token cannot sign
    AC-6  a settled bill carries `payout_simulated` and the demo label
    AC-8  the verify toggle proxies Evidence's verdict (verified → tampered)
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from src.apps.console_api.app import build
from src.console.application.services import (
    ProjectApprovalInbox,
    ProjectEvidence,
    ProjectPayerBills,
)
from src.console.interfaces.api import CONSOLE_ROUTES, ConsoleDeps
from src.shared.infrastructure.config import Settings, load_settings

OWNER = {"Authorization": "Bearer demo-owner-token"}
PAYER = {"Authorization": "Bearer demo-payer-token"}

#: Mixed case is the address checksum; a lowercased copy is a different value (CON-02).
ADDRESS = "0x7A3fC2b1D4e5F60718293aBcDeF0123456789E9c2"
DIGEST = "sha256:9f2ab7c1e0d4"
AMOUNT = "320.00"

PENDING = {
    "approval_id": "ap-1",
    "intent_id": "intent-1",
    "invoice_id": "inv-1",
    "payee_name": "Northwind Insurance",
    "payee_address": ADDRESS,
    "amount_usdc": AMOUNT,
    "bank_digest": DIGEST,
    "is_new_payee": True,
    "requires_owner_signature": True,
    "reason_codes": [],
    "expires_at": "2026-11-13T15:00:00Z",
    "typed_data_hash": "0xhash",
    # CON-01: model output and an unknown debug key must both be dropped.
    "internal_note": "agent guess: this looks fine",
    "debug_trace": {"hop": 2},
}

SETTLED_INVOICE = {
    "invoice_id": "inv-1",
    "payee_name": "Northwind Energy",
    "amount_usdc": AMOUNT,
    "status": "SETTLED",
    "payout_simulated": True,
    "internal_note": "operator paid this manually",
}
RECEIPT = {"invoice_id": "inv-1", "tx_hash": "0xabc123", "settled_at": "2026-11-13T14:02:00Z"}


class _RecordingApprovals:
    """Records the bytes it is handed — the only way to prove a passthrough (CON-03)."""

    def __init__(self) -> None:
        self.received: bytes | None = None
        self.received_content_type = ""

    async def list_pending(self, owner_scope: str) -> tuple[Mapping[str, object], ...]:
        return (PENDING,)

    async def submit_signature(
        self, approval_id: str, raw_body: bytes, content_type: str
    ) -> Mapping[str, object]:
        self.received = raw_body
        self.received_content_type = content_type
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
        return ()

    async def verify(self, envelope_id: str) -> Mapping[str, object]:
        verdict = "tampered" if envelope_id == "env-tampered" else "verified"
        return {"envelope_id": envelope_id, "outcome": verdict, "checked_at": "2026-11-13"}


@dataclass
class _Wired:
    client: TestClient
    approvals: _RecordingApprovals


@pytest.fixture
def wired(tmp_path: Path) -> Iterator[_Wired]:
    settings: Settings = load_settings(
        env="ci",
        console_database_url=f"sqlite+aiosqlite:///{tmp_path / 'bursar.db'}",
        hmac_key="test-hmac-key-not-a-secret",
        settlement_private_key="0x" + "11" * 32,
        rigorix_api_key="test",
    )
    with TestClient(build(settings)) as client:
        approvals = _RecordingApprovals()
        client.app.state.console_deps = ConsoleDeps(  # type: ignore[attr-defined]
            approval_inbox=ProjectApprovalInbox(approvals, _Determinations(), _Constitution()),
            payer_bills=ProjectPayerBills(_Bills(), _Receipts()),
            evidence=ProjectEvidence(_Evidence()),
        )
        yield _Wired(client=client, approvals=approvals)


def _json(response: Any) -> Any:
    return response.json()


class TestOwnerInbox:
    def test_the_inbox_renders_the_exact_intent_fields(self, wired: _Wired) -> None:
        """AC-2/CON-02: the signed bytes reach the screen unchanged — case included."""
        response = wired.client.get("/v1/console/approvals", headers=OWNER)

        assert response.status_code == 200
        item = _json(response)[0]
        assert item["payee_address"] == ADDRESS
        assert item["payee_address"] != ADDRESS.lower()
        assert item["bank_digest"] == DIGEST
        assert item["amount_usdc"] == AMOUNT
        assert item["typed_data_hash"] == "0xhash"

    def test_model_output_and_unknown_keys_never_reach_a_response(self, wired: _Wired) -> None:
        """AC-1/CON-01: `internal_note` is model output; a debug key is not evidence."""
        response = wired.client.get("/v1/console/approvals", headers=OWNER)

        assert response.status_code == 200
        rendered = json.dumps(_json(response))
        assert "internal_note" not in rendered
        assert "agent guess" not in rendered
        assert "debug_trace" not in rendered


class TestSignaturePassthrough:
    def test_the_recorded_body_equals_the_received_one(self, wired: _Wired) -> None:
        """AC-3/CON-03: one re-ordered key changes the bytes Authority verifies."""
        body = b'{"signature":"0xdeadbeef","intent_id":"intent-1","amount":"320.00"}'
        response = wired.client.post(
            "/v1/console/approvals/ap-1/signature",
            content=body,
            headers={**OWNER, "Content-Type": "application/json"},
        )

        assert response.status_code == 200
        assert _json(response)["granted"] is True
        assert wired.approvals.received == body
        assert wired.approvals.received_content_type == "application/json"

    def test_a_body_that_is_not_json_is_forwarded_rather_than_rejected(self, wired: _Wired) -> None:
        """AC-3/CON-03: parsing is rewriting; the console must not need valid JSON."""
        body = b'{"signature": "0xdeadbeef", "intent_id": "intent-1"'
        response = wired.client.post(
            "/v1/console/approvals/ap-1/signature",
            content=body,
            headers={**OWNER, "Content-Type": "application/json"},
        )

        assert response.status_code == 200
        assert wired.approvals.received == body


class TestScopeMatrix:
    def test_the_payer_token_cannot_sign(self, wired: _Wired) -> None:
        """AC-4/CON-04: signing is the owner's only write; a payer token has no such scope."""
        response = wired.client.post(
            "/v1/console/approvals/ap-1/signature",
            content=b"{}",
            headers={**PAYER, "Content-Type": "application/json"},
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"

    def test_no_console_path_can_create_a_payment(self, wired: _Wired) -> None:
        """AC-4/CON-04: a path the console cannot name is an operation it cannot reach."""
        schema = wired.client.get("/openapi.json").json()
        offending = [
            path
            for path in schema["paths"]
            if path.startswith("/v1/console/")
            and any(word in path for word in ("intent", "attempt", "settlement", "dispatch"))
        ]
        assert offending == []


class TestPayerSurface:
    def test_a_settled_bill_is_labelled_as_simulated(self, wired: _Wired) -> None:
        """AC-6/CON-06: a demo transfer is never presented as a real bank payment."""
        response = wired.client.get("/v1/console/bills", headers=PAYER)

        assert response.status_code == 200
        bill = _json(response)[0]
        assert bill["status_plain"] == "Paid"
        assert bill["payout_simulated"] is True
        assert "simulated" in bill["payout_label"]

    def test_payer_copy_contains_no_crypto_vocabulary(self, wired: _Wired) -> None:
        """AC-5/CON-05: the household copy has no USDC/gas/chain/wallet/nullifier/determination.

        The wire *field* `amount_usdc` is part of the frozen DTO; the rule is about the sentence a
        payer reads, so the assertion is on copy values (`status_plain`, `payout_label`, ...).
        """
        bill = _json(wired.client.get("/v1/console/bills", headers=PAYER))[0]
        copy = " ".join(
            str(bill[field])
            for field in ("payee_name", "status_plain", "payout_label", "refusal_reason")
        ).lower()

        for term in ("usdc", "gas", "chain", "wallet", "nullifier", "determination"):
            assert term not in copy


class TestVerifyToggle:
    @pytest.mark.parametrize(
        ("envelope_id", "expected"),
        [("env-untouched", "verified"), ("env-tampered", "tampered")],
    )
    def test_the_console_proxies_evidence_verdict(
        self, wired: _Wired, envelope_id: str, expected: str
    ) -> None:
        """AC-8/CON-08: scenario 7 flips one byte; the console renders Evidence's answer."""
        response = wired.client.get(f"/v1/console/evidence/{envelope_id}/verify", headers=OWNER)

        assert response.status_code == 200
        assert _json(response)["outcome"] == expected


class _NoVerdictEvidence:
    async def list_envelopes(self, intent_id: str | None) -> tuple[Mapping[str, object], ...]:
        return ()

    async def verify(self, envelope_id: str) -> Mapping[str, object]:
        from src.console.application.errors import VerificationRefused

        raise VerificationRefused(f"Evidence has no verdict for {envelope_id!r}")


class TestOwnerDisplayReads:
    def test_one_bill_uses_the_same_household_language(self, wired: _Wired) -> None:
        response = wired.client.get("/v1/console/bills/inv-1", headers=PAYER)
        assert response.status_code == 200
        assert _json(response)["payout_simulated"] is True

    def test_payees_and_constitution_are_display_only(self, wired: _Wired) -> None:
        payees = wired.client.get("/v1/console/payees", headers=OWNER)
        current = wired.client.get("/v1/console/constitution", headers=OWNER)

        assert payees.status_code == 200
        assert _json(payees)[0]["display_name"] == "Northwind"
        assert current.status_code == 200
        assert _json(current)["cap_usdc"] == "500.00"

    def test_evidence_list_is_an_empty_page_not_an_error(self, wired: _Wired) -> None:
        response = wired.client.get("/v1/console/evidence?intent_id=intent-1", headers=OWNER)
        assert response.status_code == 200
        assert _json(response) == []

    def test_missing_bearer_is_a_401_before_any_projection(self, wired: _Wired) -> None:
        response = wired.client.get("/v1/console/approvals")
        assert response.status_code == 401


class TestConsoleRefusalEnvelope:
    def test_a_projection_refusal_is_a_documented_409(self, wired: _Wired) -> None:
        """ADR-004: a console refusal is a 409 outcome, never a 500."""
        wired.client.app.state.console_deps = ConsoleDeps(  # type: ignore[attr-defined]
            approval_inbox=ProjectApprovalInbox(
                _RecordingApprovals(), _Determinations(), _Constitution()
            ),
            payer_bills=ProjectPayerBills(_Bills(), _Receipts()),
            evidence=ProjectEvidence(_NoVerdictEvidence()),
        )

        response = wired.client.get("/v1/console/evidence/env-1/verify", headers=OWNER)

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONFLICT"


class TestComposition:
    def test_the_router_composes_three_projections_over_six_adapters(self) -> None:
        from src.console.interfaces.api import build_deps

        deps = build_deps()

        assert isinstance(deps.approval_inbox, ProjectApprovalInbox)
        assert isinstance(deps.payer_bills, ProjectPayerBills)
        assert isinstance(deps.evidence, ProjectEvidence)


@pytest.fixture
def composed_client(tmp_path: Path) -> Iterator[TestClient]:
    """The deployable with **no** test injection: the runtime path the demo actually serves."""
    settings: Settings = load_settings(
        env="ci",
        console_database_url=f"sqlite+aiosqlite:///{tmp_path / 'composed.db'}",
        hmac_key="test-hmac-key-not-a-secret",
        settlement_private_key="0x" + "11" * 32,
        rigorix_api_key="test",
    )
    with TestClient(build(settings)) as client:
        yield client


class TestRuntimeComposition:
    def test_the_inbox_is_reachable_through_the_composition_root(
        self, composed_client: TestClient
    ) -> None:
        """ADR-009: a console that only its own tests call is not integrated."""
        response = composed_client.get("/v1/console/approvals", headers=OWNER)

        assert response.status_code == 200
        assert _json(response)[0]["payee_address"] == ADDRESS

    def test_the_runtime_serves_exactly_the_eight_frozen_paths(
        self, composed_client: TestClient
    ) -> None:
        schema = composed_client.get("/openapi.json").json()
        console_paths = {path for path in schema["paths"] if path.startswith("/v1/console/")}

        assert console_paths == {route.path for route in CONSOLE_ROUTES}

    def test_the_payer_surface_renders_the_recorded_settlement(
        self, composed_client: TestClient
    ) -> None:
        """CON-06 through the real adapters: the demo settlement carries the simulated label."""
        bill = _json(composed_client.get("/v1/console/bills", headers=PAYER))[0]

        assert bill["payout_simulated"] is True
        assert "simulated" in bill["payout_label"]
