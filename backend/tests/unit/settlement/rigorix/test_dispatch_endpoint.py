"""The dispatch endpoint, end to end, with fakes — never the network (SC-1, SC-2, SC-5).

Canonical: .pi/architecture/modules/settlement.md#api-endpoints
Reference: docs/contracts/settlement-contract-freeze.md §2.11

This suite boots the real router and the real `DispatchPaymentService` against a temp SQLite file, with
the three ports replaced by fakes: a gate, an intent source, a Rigorix executor and a chain gateway. That
is the wiring claim the adapter tests cannot make on their own — the endpoint reaches the use case, the
use case reaches the adapters, and a refusal comes back as the shared 409 envelope instead of a 500.

No handler here opens a socket: the fakes are plain objects, and the app's lifespan builds its own engine.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.authority.domain.ids import IntentId
from src.authority.domain.values import DeterminationVerdict
from src.settlement.application.dispatch import DispatchPaymentService
from src.settlement.domain.errors import SettlementRefusal
from src.settlement.domain.ports import CommandAck
from src.settlement.domain.settlement_order import SettlementOrder
from src.settlement.domain.values import ChainNetwork, Nullifier
from src.settlement.domain.views import DeterminationView, PaymentIntentView
from src.settlement.infrastructure.models import Base
from src.settlement.interfaces.http.router import build_router, build_services
from src.shared.domain.errors import ErrorCode
from src.shared.infrastructure.db import build_engine, build_session_factory
from src.shared.interfaces.errors import install_error_handlers

from tests.unit.settlement._fixtures import a_determination, an_anvil_network, an_intent

INTENT_ID = IntentId("intent-dispatch-1")
OWNER = {"Authorization": "Bearer demo-owner-token"}
BOUNDARY_REFUSAL = "run_command refused: no execution boundary declared (RIGORIX_SANDBOX is unset)"


class FakeIntents:
    """The Authority intent read, as a port-shaped object."""

    def __init__(self, intent: PaymentIntentView) -> None:
        self.intent = intent

    async def intent_for(self, intent_id: IntentId) -> PaymentIntentView:
        assert intent_id == self.intent.intent_id
        return self.intent


class FakeGate:
    """A determination read that can be told to refuse."""

    def __init__(self, determination: DeterminationView) -> None:
        self.determination = determination
        self.reads = 0

    async def determination_for(self, intent_id: IntentId) -> DeterminationView:
        self.reads += 1
        assert intent_id == self.determination.intent_id
        return self.determination


class FakeExecutor:
    """A `PaymentExecutor` that records the order and never touches a host."""

    def __init__(self, *, refusal: str = "") -> None:
        self.refusal = refusal
        self.orders: list[SettlementOrder] = []

    async def execute(self, order: SettlementOrder) -> CommandAck:
        self.orders.append(order)
        if self.refusal:
            raise SettlementRefusal(ErrorCode.CONFLICT, self.refusal)
        return CommandAck(
            command_ref=order.command_ref,
            accepted=True,
            execution_id=str(order.id),
            audit_uri="rigorix://audit/fake",
        )


class FakeChain:
    """The chain's read side; `is_nullifier_spent` is the only method dispatch needs (SC-5)."""

    def __init__(self, *, spent: bool = False) -> None:
        self.spent = spent
        self.reads: list[Nullifier] = []

    async def is_nullifier_spent(self, nullifier: Nullifier) -> bool:
        self.reads.append(nullifier)
        return self.spent


@dataclass
class Harness:
    client: TestClient
    gate: FakeGate
    executor: FakeExecutor
    chain: FakeChain
    network: ChainNetwork = field(default_factory=an_anvil_network)


@contextmanager
def build_harness(
    tmp_path: Path,
    *,
    verdict: DeterminationVerdict = DeterminationVerdict.ALLOW,
    executor_refusal: str = "",
    spent_on_chain: bool = False,
) -> Iterator[Harness]:
    intent = an_intent(intent_id=INTENT_ID)
    intents = FakeIntents(intent)
    gate = FakeGate(a_determination(verdict, intent_id=INTENT_ID))
    executor = FakeExecutor(refusal=executor_refusal)
    chain = FakeChain(spent=spent_on_chain)
    network = an_anvil_network()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        engine = build_engine(f"sqlite+aiosqlite:///{tmp_path / 'dispatch.db'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = build_session_factory(engine)
        application.state.session_factory = factory
        services = build_services(factory)
        services["dispatch"] = DispatchPaymentService(
            factory,
            intents=intents,
            determination=gate,
            executor=executor,
            network=network,
            chain=chain,
        )
        application.state.settlement_services = services
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    install_error_handlers(app)
    app.include_router(build_router())
    with TestClient(app) as client:
        yield Harness(client=client, gate=gate, executor=executor, chain=chain, network=network)


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[Harness]:
    with build_harness(tmp_path) as built:
        yield built


class TestSuccessfulDispatch:
    def test_dispatch_returns_201_the_order_and_the_nullifier(self, harness: Harness) -> None:
        response = harness.client.post(f"/v1/intents/{INTENT_ID}/dispatch", headers=OWNER)

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["intent_id"] == str(INTENT_ID)
        assert body["status"] == "ordered"
        # No broadcast happened here (B-1): there is no hash, and none is invented.
        assert body["tx_hash"] is None
        assert body["nullifier"].startswith("0x")
        assert body["events"] == ["SettlementOrdered"]

    def test_the_order_is_persisted_and_readable_afterwards(self, harness: Harness) -> None:
        created = harness.client.post(f"/v1/intents/{INTENT_ID}/dispatch", headers=OWNER)
        order_id = created.json()["order_id"]

        read = harness.client.get(f"/v1/orders/{order_id}", headers=OWNER)

        assert read.status_code == 200
        assert read.json()["status"] == "ordered"
        assert read.json()["amount_micro_usdc"] == 42_500_000

    def test_all_three_ports_are_reached(self, harness: Harness) -> None:
        """SC-1 (gate), SC-2 (executor gets the order), SC-5 (on-chain nullifier read)."""
        created = harness.client.post(f"/v1/intents/{INTENT_ID}/dispatch", headers=OWNER)

        assert created.status_code == 201
        assert harness.gate.reads == 1
        assert len(harness.executor.orders) == 1
        order = harness.executor.orders[0]
        assert order.command_ref == "payments.dispatch"
        assert order.command_params()["intent_id"] == str(INTENT_ID)
        assert order.command_params()["amount_usdc"] == 42_500_000
        assert order.command_params()["payee_address"] == order.payee_address.value
        assert harness.chain.reads == [order.nullifier]


class TestRefusedDispatch:
    def test_a_deny_determination_is_a_409_and_nothing_is_dispatched(self, tmp_path: Path) -> None:
        with build_harness(tmp_path, verdict=DeterminationVerdict.DENY) as harness:
            response = harness.client.post(f"/v1/intents/{INTENT_ID}/dispatch", headers=OWNER)

        assert response.status_code == 409
        envelope = response.json()["error"]
        assert envelope["code"] == "CONFLICT"
        assert "allowance" in envelope["message"]
        assert harness.executor.orders == []

    def test_a_rigorix_refusal_reaches_the_client_with_the_host_reason(
        self, tmp_path: Path
    ) -> None:
        with build_harness(tmp_path, executor_refusal=BOUNDARY_REFUSAL) as harness:
            response = harness.client.post(f"/v1/intents/{INTENT_ID}/dispatch", headers=OWNER)

        assert response.status_code == 409
        assert BOUNDARY_REFUSAL in response.json()["error"]["message"]
        assert len(harness.executor.orders) == 1

    def test_a_spent_on_chain_nullifier_refuses_before_the_command_runs(
        self, tmp_path: Path
    ) -> None:
        with build_harness(tmp_path, spent_on_chain=True) as harness:
            response = harness.client.post(f"/v1/intents/{INTENT_ID}/dispatch", headers=OWNER)

        assert response.status_code == 409
        assert "settled" in response.json()["error"]["message"]
        # SC-5: the governed command never ran — a replay produces no transaction at all.
        assert harness.executor.orders == []

    def test_a_replayed_dispatch_is_a_duplicate_settlement_and_runs_once(
        self, harness: Harness
    ) -> None:
        first = harness.client.post(f"/v1/intents/{INTENT_ID}/dispatch", headers=OWNER)
        second = harness.client.post(f"/v1/intents/{INTENT_ID}/dispatch", headers=OWNER)

        assert first.status_code == 201
        assert second.status_code == 409
        assert len(harness.executor.orders) == 1

    def test_dispatch_requires_a_settlement_scope(self, harness: Harness) -> None:
        response = harness.client.post(f"/v1/intents/{INTENT_ID}/dispatch")

        assert response.status_code == 401
