"""E2E through the public API — the Settlement context is reachable from the runtime entry path.

Canonical: .pi/architecture/decisions/ADR-009-runtime-wiring-multilang-judgment.md
Reference: .pi/architecture/modules/settlement.md#api-endpoints

These tests boot the **real composition root** (`console_api.app.build`) with a temp database, seed a
settled order through the real repositories, and exercise the frozen endpoints over HTTP. That is the
ADR-009 claim: not "the service exists and its tests pass", but "a client can reach it".

The two write endpoints answer `501` today, and the test asserts the *reason* is stated. A 501 that names
the blocker is honest; a silent success against a fake chain would be the gap ADR-009 exists to close.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker
from src.settlement.domain.settlement_order import SettlementOrder
from src.settlement.infrastructure.repositories import (
    OutboxWriter,
    SqlChainReceiptRepository,
    SqlNullifierRepository,
    SqlSettlementOrderRepository,
)
from src.shared.application.unit_of_work import session_scope
from src.shared.infrastructure.config import Settings
from src.shared.infrastructure.db import build_engine, build_session_factory

from tests.integration.settlement.conftest import an_order
from tests.unit.settlement._fixtures import a_receipt

OWNER = {"Authorization": "Bearer demo-owner-token"}

TX_HASH = "0x" + "aa" * 32


async def _seed(url: str) -> SettlementOrder:
    """Insert a SUBMITTED order, spend its nullifier and append one receipt — committed."""
    engine = build_engine(url)
    factory: async_sessionmaker = build_session_factory(engine)
    order = an_order()
    try:
        async with session_scope(factory) as session:
            orders = SqlSettlementOrderRepository(session)
            await orders.add(order)
            await SqlNullifierRepository(session).spend(order.nullifier, order.id)
            order.mark_submitted(TX_HASH, order.amount)
            await orders.save(order)
            await OutboxWriter(session).append(order.pull_events())
            await SqlChainReceiptRepository(session).append(
                a_receipt(order_id=order.id, confirmations=1, fee_micro_usdc=51)
            )
    finally:
        await engine.dispose()
    return order


@pytest.fixture
def settled(tmp_settings: Settings) -> Iterator[tuple[TestClient, SettlementOrder]]:
    from src.apps.console_api.app import build

    with TestClient(build(tmp_settings)) as client:
        # The app's lifespan created the schema; seed on the same file through a second engine.
        order = asyncio.run(_seed(tmp_settings.console_database_url))
        yield client, order


class TestReadSurface:
    def test_the_order_list_and_detail_are_reachable(
        self, settled: tuple[TestClient, SettlementOrder]
    ) -> None:
        client, order = settled

        listed = client.get("/v1/orders", headers=OWNER)
        detail = client.get(f"/v1/orders/{order.id}", headers=OWNER)

        assert listed.status_code == 200
        assert listed.json()["count"] == 1
        assert listed.json()["orders"][0]["order_id"] == str(order.id)
        assert detail.status_code == 200
        body = detail.json()
        assert body["status"] == "submitted"
        assert body["tx_hash"] == TX_HASH
        assert body["amount_micro_usdc"] == order.amount.micro_usdc
        assert body["chain_id"] == order.network.chain_id

    def test_the_receipt_exposes_gas_and_fee(
        self, settled: tuple[TestClient, SettlementOrder]
    ) -> None:
        client, order = settled

        response = client.get(f"/v1/orders/{order.id}/receipt", headers=OWNER)

        assert response.status_code == 200
        body = response.json()
        assert body["tx_hash"] == "0x" + "ef" * 32
        assert body["gas_used"] == 51_000
        assert body["fee_micro_usdc"] == 51
        assert body["status"] == "success"

    def test_the_day_cost_derives_from_receipts(
        self, settled: tuple[TestClient, SettlementOrder]
    ) -> None:
        client, _order = settled

        response = client.get(
            "/v1/receipts", params={"day": datetime.now(UTC).date().isoformat()}, headers=OWNER
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["receipts"]) == 1
        assert body["cost"]["receipt_count"] == 1
        assert body["cost"]["total_fee_micro_usdc"] == 51

    def test_the_nullifier_status_reports_the_spending_order(
        self, settled: tuple[TestClient, SettlementOrder]
    ) -> None:
        client, order = settled

        response = client.get(f"/v1/nullifiers/{order.nullifier.value}", headers=OWNER)

        assert response.status_code == 200
        assert response.json() == {
            "nullifier": order.nullifier.value,
            "spent": True,
            "order_id": str(order.id),
        }

    def test_a_missing_order_is_a_404_envelope(
        self, settled: tuple[TestClient, SettlementOrder]
    ) -> None:
        client, _order = settled

        response = client.get("/v1/orders/does-not-exist", headers=OWNER)

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"


class TestAuth:
    def test_the_read_surface_requires_a_scope(
        self, settled: tuple[TestClient, SettlementOrder]
    ) -> None:
        client, _order = settled

        assert client.get("/v1/orders").status_code == 401

    def test_a_token_without_the_scope_is_forbidden(
        self, settled: tuple[TestClient, SettlementOrder]
    ) -> None:
        client, _order = settled

        response = client.get("/v1/orders", headers={"Authorization": "Bearer demo-payer-token"})

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"


class TestBlockedWrites:
    def test_dispatch_states_the_contract_blocker(
        self, settled: tuple[TestClient, SettlementOrder]
    ) -> None:
        client, order = settled

        response = client.post(f"/v1/intents/{order.intent_id}/dispatch", headers=OWNER)

        assert response.status_code == 501
        # The shared ADR-004 handler wraps an HTTPException in the error envelope; the message is where
        # the blocker must be named (a 501 with no reason is indistinguishable from a bug).
        assert "SC-3" in response.json()["error"]["message"]

    def test_anchor_states_the_adapter_gap(
        self, settled: tuple[TestClient, SettlementOrder]
    ) -> None:
        client, _order = settled

        response = client.post("/v1/anchors", headers=OWNER, json={"hash": "ab" * 32})

        assert response.status_code == 501
        assert "ChainGateway" in response.json()["error"]["message"]
