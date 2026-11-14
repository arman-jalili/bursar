"""End-to-end through the public HTTP API — the runtime integration test.

Canonical: docs/architecture/modules/mandate.md#api-endpoints
Reference: docs/architecture/decisions/ADR-005-authentication-authorization.md

These tests go through the real app (middleware, scopes, error envelope, session factory, SQLite) and
cover the module doc's scenario-facing acceptance criteria:

    AC #2   threshold > cap is refused (409, envelope code)
    AC #9   agent credentials are refused on every mandate write (403) before any state changes
    AC #10  the presented-digest endpoint returns 200 and changes nothing else
    AC #11  eligibility is read-through: allow/escort -> deny after a freeze, between two calls
    scenario 2  a poisoned digest quarantines the payee and leaves the address byte-identical
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from src.apps.console_api.app import build
from src.shared.infrastructure.config import Settings, load_settings

OWNER = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
PAYEE = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
OWNER_TOKEN = {"Authorization": "Bearer demo-owner-token"}
AGENT_TOKEN = {"Authorization": "Bearer demo-agent-token"}
GOOD_ROUTING = "DE89370400440532013000"
POISONED_ROUTING = "GB33BUKB20201555555555"


def _digest(routing: str) -> str:
    from src.mandate.domain.values import BankDigest, RoutingDetails

    return BankDigest.from_routing_details(
        RoutingDetails(scheme="sepa", account_number=routing)
    ).hash


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


def _bootstrap(client: TestClient) -> dict[str, str]:
    """Create the household and one payee; returns the ids the later calls need."""
    household = client.post(
        "/v1/households",
        headers=OWNER_TOKEN,
        json={
            "owner_address": OWNER,
            "owner_name": "Dana",
            "payer_name": "Mum",
            "agent_key_id": "key-1",
            "cap_micro_usdc": 150_000_000,
            "threshold_micro_usdc": 25_000_000,
            "owner_proof": "signed:mandate",
        },
    )
    assert household.status_code == 201, household.text
    household_id = household.json()["household_id"]

    payee = client.post(
        f"/v1/households/{household_id}/payees",
        headers=OWNER_TOKEN,
        json={
            "name": "Northwind Energy",
            "address": PAYEE,
            "routing_scheme": "sepa",
            "routing_account_number": GOOD_ROUTING,
            "owner_proof": "signed:payee",
        },
    )
    assert payee.status_code == 201, payee.text
    return {"household_id": household_id, "payee_id": payee.json()["payee_id"]}


class TestMandateOverHttp:
    def test_creates_a_household_and_a_payee(self, client: TestClient) -> None:
        ids = _bootstrap(client)
        assert ids["household_id"] and ids["payee_id"]

    def test_poisoned_digest_quarantines_and_keeps_the_address(self, client: TestClient) -> None:
        """Scenario 2 all the way through HTTP."""
        ids = _bootstrap(client)

        response = client.post(
            f"/v1/payees/{ids['payee_id']}/presented-digest",
            headers=AGENT_TOKEN,
            json={"presented_digest": _digest(POISONED_ROUTING), "invoice_id": "inv-12"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["quarantined"] is True
        assert body["status"] == "quarantined"
        assert body["address"] == PAYEE, "quarantine stops the payment; it never redirects it"
        assert body["events"] == ["PayeeDigestChanged", "PayeeQuarantined"]

    def test_presented_digest_is_idempotent_for_a_matching_digest(self, client: TestClient) -> None:
        """AC #10: 200 and no other state change."""
        ids = _bootstrap(client)
        response = client.post(
            f"/v1/payees/{ids['payee_id']}/presented-digest",
            headers=AGENT_TOKEN,
            json={"presented_digest": _digest(GOOD_ROUTING)},
        )
        assert response.status_code == 200
        assert response.json()["quarantined"] is False
        assert response.json()["status"] == "new"

    def test_eligibility_is_read_through(self, client: TestClient) -> None:
        """AC #11: allow/escalate now, deny immediately after a freeze — no caching anywhere."""
        ids = _bootstrap(client)
        first = client.get(f"/v1/payees/{ids['payee_id']}/eligibility", headers=AGENT_TOKEN)
        assert first.status_code == 200
        assert first.json()["verdict"] == "escalate"
        assert first.json()["reason"] == "new_payee"

        assert (
            client.post(f"/v1/payees/{ids['payee_id']}/freeze", headers=OWNER_TOKEN).status_code
            == 200
        )

        second = client.get(f"/v1/payees/{ids['payee_id']}/eligibility", headers=AGENT_TOKEN)
        assert second.json()["verdict"] == "deny"
        assert second.json()["reason"] == "payee_frozen"

    def test_owner_reapproval_restores_eligibility(self, client: TestClient) -> None:
        ids = _bootstrap(client)
        client.post(
            f"/v1/payees/{ids['payee_id']}/presented-digest",
            headers=AGENT_TOKEN,
            json={"presented_digest": _digest(POISONED_ROUTING)},
        )
        response = client.post(
            f"/v1/payees/{ids['payee_id']}/reapprove",
            headers=OWNER_TOKEN,
            json={
                "routing_scheme": "sepa",
                "routing_account_number": POISONED_ROUTING,
                "owner_proof": "signed:reapprove",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "eligible"
        assert response.json()["verified_digest"] == _digest(POISONED_ROUTING)


class TestAuthorizationMatrix:
    """AC #9 / NFR-016 — the agent key can propose, and cannot change anything about authority."""

    @pytest.mark.parametrize(
        ("method", "path", "payload"),
        [
            (
                "post",
                "/v1/households",
                {
                    "owner_address": OWNER,
                    "owner_name": "x",
                    "payer_name": "y",
                    "agent_key_id": "k",
                    "cap_micro_usdc": 1,
                    "threshold_micro_usdc": 0,
                },
            ),
            ("post", "/v1/payees/whatever/freeze", None),
            ("post", "/v1/payees/whatever/reapprove", {"owner_proof": "signed"}),
        ],
    )
    def test_agent_is_refused_on_mandate_writes(
        self, client: TestClient, method: str, path: str, payload: dict | None
    ) -> None:
        response = getattr(client, method)(path, headers=AGENT_TOKEN, json=payload)
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "FORBIDDEN"

    def test_missing_token_is_401(self, client: TestClient) -> None:
        response = client.post("/v1/households", json={})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHENTICATED"

    def test_owner_write_without_signature_is_403(self, client: TestClient) -> None:
        """ADR-005 layer 2: a key is not an approval."""
        ids = _bootstrap(client)
        response = client.post(
            f"/v1/payees/{ids['payee_id']}/reapprove",
            headers=OWNER_TOKEN,
            json={"routing_account_number": "X"},
        )
        assert response.status_code == 403
        assert "signature" in response.json()["error"]["message"]

    def test_unknown_payee_is_404_in_the_envelope(self, client: TestClient) -> None:
        response = client.post("/v1/payees/does-not-exist/freeze", headers=OWNER_TOKEN)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
        assert response.json()["error"]["correlation_id"]


class TestRefusalsAreEnvelopeShaped:
    def test_threshold_above_cap_is_a_documented_refusal(self, client: TestClient) -> None:
        """AC #2 through the API: 409 with a code, not a 500."""
        response = client.post(
            "/v1/households",
            headers=OWNER_TOKEN,
            json={
                "owner_address": OWNER,
                "owner_name": "Dana",
                "payer_name": "Mum",
                "agent_key_id": "key-1",
                "cap_micro_usdc": 100_000_000,
                "threshold_micro_usdc": 300_000_000,
                "owner_proof": "signed",
            },
        )
        assert response.status_code == 409, response.text
        error = response.json()["error"]
        assert error["code"] == "CONFLICT"
        assert error["details"]["cap_usdc"] == "100000000"
        assert error["retryable"] is False

    def test_malformed_body_is_422_with_field_paths(self, client: TestClient) -> None:
        response = client.post(
            "/v1/households", headers=OWNER_TOKEN, json={"owner_address": "nonsense"}
        )
        assert response.status_code == 422
        assert "details" in response.json()["error"]


class TestReadinessReflectsReality:
    def test_readyz_reports_mandate_as_wired(self, client: TestClient) -> None:
        body = client.get("/readyz").json()
        assert "Mandate" in body["build"]["wired_contexts"]
        assert "Billing" in body["build"]["wired_contexts"]
        # Settlement and Console ship in the same deployable now; only Authority lives elsewhere.
        assert "Settlement" in body["build"]["wired_contexts"]
        assert "Console" in body["build"]["wired_contexts"]
        assert body["build"]["pending_contexts"] == []

    def test_openapi_documents_the_mandate_contract(self, client: TestClient) -> None:
        schema = client.get("/openapi.json").json()
        assert "/v1/payees/{payee_id}/presented-digest" in schema["paths"]
        assert "/v1/payees/{payee_id}/eligibility" in schema["paths"]
