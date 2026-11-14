"""End-to-end through the public Authority HTTP API — the runtime integration test.

Canonical: .pi/architecture/modules/authority.md#api-endpoints
Reference: docs/contracts/authority-contract-freeze.md §2.9

These tests go through the real deployable (`authority_service.app.build`): migrations, session factory,
scope checks, the ADR-004 envelope, the SQL ledger and the outbox. Nothing is mocked except Billing, and
Billing is not mocked — its persistence layer does not exist yet, so `POST /v1/attempts/{id}/evaluate`
fails closed with `503 retryable`. That absence is asserted, because a stand-in that invented an invoice
would be the exact failure ADR-007 forbids.

Covered invariants:

    AC 11    a refusal is a non-2xx (409), never a 200 that "looks helpful"
    A-2      routing fields in the precondition body are rejected, not ignored
    A-3/A-4  the code-constructed intent, not the caller, decides the amount and signature requirement
    A-5/A-8  a DENY is persisted with its reason code and leaves the ledger untouched
    A-9      a second payment beyond the cap is refused; the first reservation still stands
    A-10     a settlement outcome resolves the hold exactly once; a replay is 409
    A-13…A-15 the owner's key signs the bound digest; another key is refused
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from src.apps.authority_service.app import build
from src.authority.infrastructure.eip712 import sign_digest
from src.authority.infrastructure.models import OutboxRow
from src.mandate.domain.values import BankDigest, RoutingDetails
from src.mandate.infrastructure.models import (
    ConstitutionRow,
    ConstitutionVersionRow,
    HouseholdRow,
    PayeeRow,
)
from src.shared.infrastructure.config import Settings, load_settings
from src.shared.infrastructure.db import build_engine, build_session_factory

# Anvil/Hardhat account #0 — the household owner in these fixtures.
OWNER = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
OWNER_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
# Anvil account #1 — a valid signer, but not *this* owner (A-15).
STRANGER_KEY = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
PAYEE = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"

OWNER_TOKEN = {"Authorization": "Bearer demo-owner-token"}
AGENT_TOKEN = {"Authorization": "Bearer demo-agent-token"}
SETTLEMENT_TOKEN = {"Authorization": "Bearer demo-settlement-token"}

CAP = 150_000_000  # 150 USDC
THRESHOLD = 25_000_000  # 25 USDC


def _digest(account: str = "DE89370400440532013000") -> str:
    return BankDigest.from_routing_details(
        RoutingDetails(scheme="sepa", account_number=account)
    ).hash


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return load_settings(
        env="ci",
        authority_database_url=f"sqlite+aiosqlite:///{tmp_path / 'authority.db'}",
        console_database_url=f"sqlite+aiosqlite:///{tmp_path / 'bursar.db'}",
        hmac_key="test-hmac-key-not-a-secret",
        settlement_private_key="0x" + "11" * 32,
        rigorix_api_key="test-rigorix-key",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """The real composition root, so a test cannot pass while the runtime has no routers."""
    with TestClient(build(settings)) as test_client:
        yield test_client


def _seed(settings: Settings, *, payee_status: str = "eligible", cap: int = CAP) -> None:
    """Write Mandate's rows directly — Authority must *read* them, not own them (A-2, A-6)."""
    assert settings.authority_database_url is not None

    async def _run() -> None:
        engine = build_engine(settings.authority_database_url)
        factory = build_session_factory(engine)
        try:
            async with factory() as session:
                session.add(
                    HouseholdRow(
                        id="hh-1",
                        owner_id="owner-1",
                        owner_address=OWNER,
                        owner_name="Dana",
                        payer_id="payer-1",
                        payer_name="Mum",
                        payer_contact="",
                        agent_id="agent-1",
                        agent_key_id="key-1",
                        agent_enabled=True,
                        constitution_id="c-1",
                        version=1,
                    )
                )
                session.add(ConstitutionRow(id="c-1", household_id="hh-1", version=1))
                session.add(
                    ConstitutionVersionRow(
                        constitution_id="c-1",
                        household_id="hh-1",
                        number=3,
                        cap_micro_usdc=cap,
                        threshold_micro_usdc=THRESHOLD,
                        require_signature_for_new_payee=True,
                        content_hash="content-hash",
                        status="in_force",
                    )
                )
                session.add(
                    PayeeRow(
                        id="payee-1",
                        household_id="hh-1",
                        name="Northwind Energy",
                        address=PAYEE,
                        verified_digest=_digest(),
                        status=payee_status,
                        version=1,
                    )
                )
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _precondition(
    client: TestClient,
    *,
    amount: int,
    invoice_id: str = "inv-12",
    headers: dict[str, str] | None = None,
) -> object:
    return client.post(
        "/v1/precondition/check",
        headers=headers or AGENT_TOKEN,
        json={
            "intent_id": "rigorix-intent-1",
            "invoice_id": invoice_id,
            "payee_id": "payee-1",
            "amount_micro_usdc": amount,
        },
    )


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _scalar(settings: Settings, statement: object) -> object:
    assert settings.authority_database_url is not None

    async def _run() -> object:
        engine = build_engine(settings.authority_database_url)
        factory = build_session_factory(engine)
        try:
            async with factory() as session:
                return await session.scalar(statement)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


class TestOnlyTwoHundredsAuthoriseDispatch:
    def test_a_payment_within_the_threshold_is_allowed(
        self, client: TestClient, settings: Settings
    ) -> None:
        """AC 11: `200` + `decision == allow` is the only shape that authorises a dispatch."""
        _seed(settings)
        response = _precondition(client, amount=12_000_000)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["decision"] == "allow"
        assert body["reason_codes"] == []
        assert body["determination_id"]

        ledger = client.get(f"/v1/ledger/{_today()}", headers=OWNER_TOKEN)
        assert ledger.status_code == 200, ledger.text
        assert ledger.json()["reserved_micro_usdc"] == 12_000_000
        assert ledger.json()["headroom_micro_usdc"] == CAP - 12_000_000

    def test_a_new_payee_escalates_and_appears_in_the_owner_inbox(
        self, client: TestClient, settings: Settings
    ) -> None:
        """A-4: the new-payee flag is derived, and escalation opens exactly one signature request."""
        _seed(settings, payee_status="new")
        response = _precondition(client, amount=42_500_000)

        assert response.status_code == 200, response.text
        assert response.json()["decision"] == "escalate"

        inbox = client.get("/v1/approvals?status=pending", headers=OWNER_TOKEN)
        assert inbox.status_code == 200, inbox.text
        items = inbox.json()
        assert len(items) == 1
        assert items[0]["status"] == "pending"
        assert items[0]["typed_data_hash"]

    def test_a_frozen_payee_is_refused_with_409_and_a_persisted_determination(
        self, client: TestClient, settings: Settings
    ) -> None:
        """A-5/A-8: a documented 409, a reason code, and no reservation left behind."""
        _seed(settings, payee_status="frozen")
        response = _precondition(client, amount=12_000_000)

        assert response.status_code == 409, response.text
        error = response.json()["error"]
        assert error["code"] == "PAYEE_FROZEN"
        assert error["retryable"] is False
        assert error["correlation_id"]
        assert error["details"]["reason_codes"] == "payee_frozen"

        intent_id = error["details"]["intent_id"]
        determination = client.get(f"/v1/intents/{intent_id}/determination", headers=OWNER_TOKEN)
        assert determination.status_code == 200, determination.text
        assert determination.json()["verdict"] == "deny"
        assert determination.json()["reason_codes"] == ["payee_frozen"]
        assert determination.json()["constitution_version"] == 3

        ledger = client.get(f"/v1/ledger/{_today()}", headers=OWNER_TOKEN)
        assert ledger.status_code == 200
        assert ledger.json()["reserved_micro_usdc"] == 0, "a refusal reserves nothing (A-8)"

    def test_six_invoices_against_the_cap_refuse_the_seventh(
        self, client: TestClient, settings: Settings
    ) -> None:
        """Scenario 4 / A-9: six 25 USDC bills exhaust a 150 USDC cap; the seventh is refused.

        Paying exactly the threshold auto-pays (A-4 uses a strict `>`), so each of the six is an
        `allow` that really reserves — the seventh then finds zero headroom and is denied, with the six
        holds intact.
        """
        _seed(settings)
        for number in range(6):
            allowed = _precondition(client, amount=25_000_000, invoice_id=f"inv-{number}")
            assert allowed.status_code == 200, allowed.text  # type: ignore[union-attr]
            assert allowed.json()["decision"] == "allow"  # type: ignore[union-attr]

        refused = _precondition(client, amount=25_000_000, invoice_id="inv-7")
        assert refused.status_code == 409, refused.text  # type: ignore[union-attr]
        assert refused.json()["error"]["code"] == "CAP_EXCEEDED"  # type: ignore[union-attr]

        ledger = client.get(f"/v1/ledger/{_today()}", headers=OWNER_TOKEN).json()
        assert ledger["reserved_micro_usdc"] == CAP
        assert ledger["headroom_micro_usdc"] == 0

    def test_routing_fields_in_the_body_are_rejected(
        self, client: TestClient, settings: Settings
    ) -> None:
        """A-2: a caller cannot inject a destination, and is not silently ignored either."""
        _seed(settings)
        response = client.post(
            "/v1/precondition/check",
            headers=AGENT_TOKEN,
            json={
                "intent_id": "i-1",
                "invoice_id": "inv-12",
                "payee_id": "payee-1",
                "amount_micro_usdc": 1_000_000,
                "payee_address": "0x000000000000000000000000000000000000dEaD",
            },
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "VALIDATION_FAILED"


class TestScopeEnforcement:
    def test_owner_cannot_evaluate(self, client: TestClient, settings: Settings) -> None:
        """The credential that signs is not the credential that decides (ADR-005)."""
        _seed(settings)
        response = client.post("/v1/attempts/attempt-7/evaluate", headers=OWNER_TOKEN)
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "FORBIDDEN"
        assert response.json()["error"]["details"]["required_scope"] == "authority:evaluate"

    def test_agent_evaluate_fails_closed_while_billing_is_unavailable(
        self, client: TestClient, settings: Settings
    ) -> None:
        """AC 11: the agent may ask; with no Billing read the answer is 503, never a guess."""
        _seed(settings)
        response = client.post("/v1/attempts/attempt-7/evaluate", headers=AGENT_TOKEN)
        assert response.status_code == 503, response.text
        assert response.json()["error"]["retryable"] is True

    def test_missing_token_is_401(self, client: TestClient) -> None:
        response = client.post("/v1/precondition/check", json={})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHENTICATED"

    def test_agent_cannot_read_the_ledger(self, client: TestClient, settings: Settings) -> None:
        _seed(settings)
        response = client.get(f"/v1/ledger/{_today()}", headers=AGENT_TOKEN)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"


class TestSignatureBindsTheOwner:
    def _escalated_approval(self, client: TestClient, settings: Settings) -> dict[str, str]:
        _seed(settings, payee_status="new")
        assert _precondition(client, amount=42_500_000).status_code == 200  # type: ignore[union-attr]
        items = client.get("/v1/approvals?status=pending", headers=OWNER_TOKEN).json()
        assert items, "an escalation must open a signature request (A-13)"
        return items[0]

    def test_the_owner_signature_grants_and_reserves(
        self, client: TestClient, settings: Settings
    ) -> None:
        """A-13/A-15: the owner's key over the bound digest authorises dispatch."""
        approval = self._escalated_approval(client, settings)
        signature = sign_digest(approval["typed_data_hash"], OWNER_KEY)

        response = client.post(
            f"/v1/approvals/{approval['approval_id']}/signature",
            headers=OWNER_TOKEN,
            json={"signature_hex": signature},
        )
        assert response.status_code == 200, response.text
        assert response.json()["granted"] is True

        ledger = client.get(f"/v1/ledger/{_today()}", headers=OWNER_TOKEN).json()
        assert ledger["reserved_micro_usdc"] == 42_500_000

    def test_another_key_is_refused_as_approval_invalid(
        self, client: TestClient, settings: Settings
    ) -> None:
        """A-15: a valid signature from a different key is not the owner's authority."""
        approval = self._escalated_approval(client, settings)
        signature = sign_digest(approval["typed_data_hash"], STRANGER_KEY)

        response = client.post(
            f"/v1/approvals/{approval['approval_id']}/signature",
            headers=OWNER_TOKEN,
            json={"signature_hex": signature},
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "APPROVAL_INVALID"

        ledger = client.get(f"/v1/ledger/{_today()}", headers=OWNER_TOKEN).json()
        assert ledger["reserved_micro_usdc"] == 0, "a refused signature has no side effect"

    def test_a_replayed_signature_is_refused_and_reserves_once(
        self, client: TestClient, settings: Settings
    ) -> None:
        """A-14: the same signature cannot dispatch twice."""
        approval = self._escalated_approval(client, settings)
        signature = sign_digest(approval["typed_data_hash"], OWNER_KEY)
        payload = {"signature_hex": signature}

        first = client.post(
            f"/v1/approvals/{approval['approval_id']}/signature",
            headers=OWNER_TOKEN,
            json=payload,
        )
        assert first.status_code == 200, first.text

        replay = client.post(
            f"/v1/approvals/{approval['approval_id']}/signature",
            headers=OWNER_TOKEN,
            json=payload,
        )
        assert replay.status_code == 409, replay.text
        assert replay.json()["error"]["code"] == "APPROVAL_INVALID"

        ledger = client.get(f"/v1/ledger/{_today()}", headers=OWNER_TOKEN).json()
        assert ledger["reserved_micro_usdc"] == 42_500_000


class TestSettlementReconcilesOnce:
    def _reservation_id(self, settings: Settings) -> str:
        payload = _scalar(
            settings,
            select(OutboxRow.payload).where(OutboxRow.event_name == "PaymentAllowed"),
        )
        assert isinstance(payload, str)
        return json.loads(payload)["reservation_id"]

    def test_confirmed_settlement_commits_the_hold_once(
        self, client: TestClient, settings: Settings
    ) -> None:
        """A-10/A-11: confirmed moves reserved -> committed, and a replay is a documented 409."""
        _seed(settings)
        assert _precondition(client, amount=12_000_000).status_code == 200  # type: ignore[union-attr]
        reservation_id = self._reservation_id(settings)

        response = client.post(
            f"/v1/settlements/{reservation_id}/outcome",
            headers=SETTLEMENT_TOKEN,
            json={"outcome": "confirmed", "tx_hash": "0xabc"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["committed_micro_usdc"] == 12_000_000
        assert body["reserved_micro_usdc"] == 0
        assert body["headroom_micro_usdc"] == CAP - 12_000_000

        replay = client.post(
            f"/v1/settlements/{reservation_id}/outcome",
            headers=SETTLEMENT_TOKEN,
            json={"outcome": "reverted", "tx_hash": "0xdef"},
        )
        assert replay.status_code == 409, replay.text
        assert replay.json()["error"]["code"] == "CONFLICT"

    def test_unknown_reservation_is_404(self, client: TestClient, settings: Settings) -> None:
        _seed(settings)
        response = client.post(
            "/v1/settlements/does-not-exist/outcome",
            headers=SETTLEMENT_TOKEN,
            json={"outcome": "reverted", "tx_hash": ""},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"


class TestReadinessReflectsReality:
    def test_readyz_reports_authority_as_wired(self, client: TestClient) -> None:
        body = client.get("/readyz").json()
        assert "Authority" in body["build"]["wired_contexts"]
        assert body["build"]["pending_contexts"] == []

    def test_openapi_documents_the_whole_contract(self, client: TestClient) -> None:
        paths = client.get("/openapi.json").json()["paths"]
        for path in (
            "/v1/precondition/check",
            "/v1/attempts/{attempt_id}/evaluate",
            "/v1/intents/{intent_id}",
            "/v1/intents/{intent_id}/determination",
            "/v1/ledger/{day}",
            "/v1/approvals",
            "/v1/approvals/{approval_id}/signature",
            "/v1/settlements/{reservation_id}/outcome",
        ):
            assert path in paths, path

    def test_an_unknown_intent_is_404_in_the_envelope(
        self, client: TestClient, settings: Settings
    ) -> None:
        _seed(settings)
        response = client.get("/v1/intents/nope", headers=OWNER_TOKEN)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"

    def test_a_day_with_no_ledger_row_is_404(self, client: TestClient) -> None:
        response = client.get("/v1/ledger/1999-01-01", headers=OWNER_TOKEN)
        assert response.status_code == 404
