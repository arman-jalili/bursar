"""Billing end-to-end through the public HTTP API.

Canonical: docs/architecture/modules/billing.md#api-endpoints
Reference: docs/contracts/billing-contract-freeze.md §2.10

These go through the real app (middleware, scope checks, the shared error envelope, SQLite):

    AC #2  a replay returns the original invoice and a `DuplicateInvoiceDetected` fact
    AC #4  a proposal carrying `payee_address`/`command`/`cap`/`threshold` gets `422 PROPOSAL_REJECTED`
           and persists zero attempts
    AC #3  a second proposal gets `409`
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from src.apps.console_api.app import build
from src.shared.infrastructure.config import Settings, load_settings

AGENT_TOKEN = {"Authorization": "Bearer demo-agent-token"}
OWNER_TOKEN = {"Authorization": "Bearer demo-owner-token"}
CONSOLE_TOKEN = {"Authorization": "Bearer demo-payer-token"}

DOCUMENT = {
    "issuer": "Northwind Energy",
    "invoice_number": "INV-2026-0042",
    "amount_usdc": "42.50",
    "due_date": "2026-11-20",
}
DIGEST = "a" * 64


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings: Settings = load_settings(
        env="ci",
        console_database_url=f"sqlite+aiosqlite:///{tmp_path / 'bursar.db'}",
        hmac_key="test-key",
        settlement_private_key="0x" + "11" * 32,
        rigorix_api_key="test",
    )
    with TestClient(build(settings)) as test_client:
        yield test_client


def _record(client: TestClient, document: dict[str, object] | None = None) -> dict[str, Any]:
    response = client.post(
        "/v1/invoices",
        headers=AGENT_TOKEN,
        json={
            "payee_id": "payee-1",
            "amount_micro_usdc": 42_500_000,
            "due_date": "2026-11-20",
            "document": document if document is not None else DOCUMENT,
            "presented_digest": DIGEST,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestInvoiceHttp:
    def test_records_an_invoice_and_carries_the_frozen_events(self, client: TestClient) -> None:
        body = _record(client)
        assert body["events"] == ["InvoiceRecorded"]
        assert body["duplicate"] is False
        assert body["invoice"]["status"] == "received"
        assert body["invoice"]["payee_id"] == "payee-1"
        assert body["invoice"]["presented_digest"] == DIGEST

    def test_a_replay_returns_the_original_and_flags_the_fact(self, client: TestClient) -> None:
        """AC #2 over the wire."""
        first = _record(client)
        second = _record(client)

        assert second["duplicate"] is True
        assert second["invoice"]["invoice_id"] == first["invoice"]["invoice_id"]
        assert "DuplicateInvoiceDetected" in second["events"]

    def test_reads_back_through_the_console_scopes(self, client: TestClient) -> None:
        body = _record(client)
        invoice_id = body["invoice"]["invoice_id"]

        single = client.get(f"/v1/invoices/{invoice_id}", headers=CONSOLE_TOKEN)
        listing = client.get("/v1/invoices", headers=CONSOLE_TOKEN)

        assert single.status_code == 200
        assert single.json()["invoice_id"] == invoice_id
        assert listing.status_code == 200
        assert [item["invoice_id"] for item in listing.json()["items"]] == [invoice_id]


class TestProposalHttp:
    @pytest.mark.parametrize(
        "payload",
        [
            {"payee_address": "0xATTACKER"},
            {"command": "payments.dispatch"},
            {"cap": 999_000_000},
            {"threshold": 1},
        ],
    )
    def test_a_forbidden_field_is_rejected_and_persists_nothing(
        self, client: TestClient, payload: dict[str, object]
    ) -> None:
        """AC #4: 422 PROPOSAL_REJECTED, and the invoice is still payable afterwards."""
        invoice_id = _record(client)["invoice"]["invoice_id"]

        refused = client.post(
            "/v1/attempts",
            headers=AGENT_TOKEN,
            json={"invoice_id": invoice_id, **payload},
        )

        assert refused.status_code == 422, refused.text
        assert refused.json()["error"]["code"] == "PROPOSAL_REJECTED"
        offending = refused.json()["error"]["details"]["offending_fields"]
        assert next(iter(payload)) in offending

        # Zero attempts persisted: an honest proposal now succeeds.
        accepted = client.post("/v1/attempts", headers=AGENT_TOKEN, json={"invoice_id": invoice_id})
        assert accepted.status_code == 201, accepted.text
        assert accepted.json()["status"] == "proposed"

    def test_a_second_proposal_is_a_conflict(self, client: TestClient) -> None:
        """AC #3 over the wire: exactly one active attempt."""
        invoice_id = _record(client)["invoice"]["invoice_id"]
        first = client.post("/v1/attempts", headers=AGENT_TOKEN, json={"invoice_id": invoice_id})
        assert first.status_code == 201

        second = client.post("/v1/attempts", headers=AGENT_TOKEN, json={"invoice_id": invoice_id})

        assert second.status_code == 409
        assert second.json()["error"]["details"]["status"] == "in_flight"

    def test_an_edited_amount_is_refused(self, client: TestClient) -> None:
        """B-6: the proposed amount must equal the invoice amount."""
        invoice_id = _record(client)["invoice"]["invoice_id"]

        refused = client.post(
            "/v1/attempts",
            headers=AGENT_TOKEN,
            json={"invoice_id": invoice_id, "proposed_amount_micro_usdc": 25_000_000},
        )

        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "AMOUNT_MISMATCH"

    def test_the_agent_scope_is_required(self, client: TestClient) -> None:
        invoice_id = _record(client)["invoice"]["invoice_id"]
        refused = client.post(
            "/v1/attempts", headers=CONSOLE_TOKEN, json={"invoice_id": invoice_id}
        )
        assert refused.status_code == 403
        assert refused.json()["error"]["code"] == "FORBIDDEN"


class TestTheProposersRead:
    """`/v1/invoices/open` is the one read the agent's `billing:read` grant buys.

    The grant existed before the route did, which meant the proposer could propose work it had no
    way to find. These tests pin the two properties that make the route safe to grant: it is
    scoped, and it does not hand back invoices that already have a decision.
    """

    def test_the_agent_can_read_what_it_may_propose(self, client: TestClient) -> None:
        invoice_id = _record(client)["invoice"]["invoice_id"]

        response = client.get("/v1/invoices/open", headers=AGENT_TOKEN)

        assert response.status_code == 200, response.text
        assert invoice_id in {item["invoice_id"] for item in response.json()["items"]}

    def test_the_agent_cannot_read_the_console_read_models(self, client: TestClient) -> None:
        """The narrow route must not be a door to the ledger: `/v1/invoices` stays `console:read`."""
        assert client.get("/v1/invoices", headers=AGENT_TOKEN).status_code == 403

    def test_a_proposed_invoice_leaves_the_open_list(self, client: TestClient) -> None:
        """`in_flight` means someone is already paying it; proposing again is the 409 we refuse."""
        invoice_id = _record(client)["invoice"]["invoice_id"]
        proposed = client.post("/v1/attempts", headers=AGENT_TOKEN, json={"invoice_id": invoice_id})
        assert proposed.status_code == 201, proposed.text

        open_ids = {item["invoice_id"] for item in client.get(
            "/v1/invoices/open", headers=AGENT_TOKEN
        ).json()["items"]}

        assert invoice_id not in open_ids
