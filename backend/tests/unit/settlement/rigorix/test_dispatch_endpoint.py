"""The dispatch endpoint, end to end, with fakes — never the network (SC-1, SC-2, SC-3, SC-5).

Canonical: .pi/architecture/modules/settlement.md#api-endpoints
Reference: docs/contracts/settlement-contract-freeze.md §2.11

This suite boots the real router and the real `DispatchPaymentService` against a temp SQLite file, with
the three ports replaced by fakes: a gate, an intent source, a Rigorix executor and a chain gateway. That
is the wiring claim the adapter tests cannot make on their own — the endpoint reaches the use case, the
use case reaches the adapters, and a refusal comes back as the shared 409 envelope instead of a 500.

The two-phase order is what the assertions are shaped around: `prepare` signs (hash known, nothing sent),
the hash is persisted while the status is `signed`, and only then does the governed command run. A refusal
from the governed step is therefore not a rollback — the order keeps its hash and stays `signed`.

No handler here opens a socket: the fakes are plain objects, and the app's lifespan builds its own engine.
"""

from __future__ import annotations

import hashlib
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
from src.settlement.domain.ports import CommandAck, SignedPayment
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


def a_hash(order_id: str) -> str:
    """A deterministic 32-byte stand-in for `eth_account`'s hash — never a real transaction."""
    return "0x" + hashlib.sha256(order_id.encode()).hexdigest()


def signed_bytes(order_id: str) -> str:
    """A deterministic stand-in for the signed bytes; the fake hashes them to `a_hash`."""
    return "0x02f8" + hashlib.sha256(order_id.encode()).hexdigest()[:60]


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
    """A `PaymentExecutor` that records what it was handed and never touches a host.

    `seen` captures `(tx_hash, status, raw_transaction)` **at the moment the governed step runs**, which
    is the ordering SC-3 is about: the hash and the signed bytes must already be there, and the order
    must still be `signed` (not `submitted`).
    """

    def __init__(self, *, refusal: str = "") -> None:
        self.refusal = refusal
        self.orders: list[SettlementOrder] = []
        self.seen: list[tuple[str | None, str, str]] = []

    async def execute(self, order: SettlementOrder) -> CommandAck:
        self.orders.append(order)
        raw = str(order.command_params()["raw_transaction"])
        self.seen.append((order.tx_hash, order.status.value, raw))
        if self.refusal:
            raise SettlementRefusal(ErrorCode.CONFLICT, self.refusal)
        return CommandAck(
            command_ref=order.command_ref,
            accepted=True,
            execution_id=str(order.id),
            audit_uri="rigorix://audit/fake",
        )


class FakeChain:
    """The chain at the port boundary: signs nothing real, sends nothing anywhere."""

    def __init__(self, *, spent: bool = False, prepare_refusal: str = "") -> None:
        self.spent = spent
        self.prepare_refusal = prepare_refusal
        self.reads: list[Nullifier] = []
        self.prepared: list[SettlementOrder] = []
        self.broadcast: list[SignedPayment] = []

    async def is_nullifier_spent(self, nullifier: Nullifier) -> bool:
        self.reads.append(nullifier)
        return self.spent

    async def prepare(self, order: SettlementOrder) -> SignedPayment:
        self.prepared.append(order)
        if self.prepare_refusal:
            raise SettlementRefusal(ErrorCode.CONFLICT, self.prepare_refusal)
        return SignedPayment(
            tx_hash=a_hash(str(order.id)), raw_transaction=signed_bytes(str(order.id))
        )

    async def broadcast(self, signed: SignedPayment) -> None:
        self.broadcast.append(signed)

    async def receipt(self, tx_hash: str) -> object | None:
        return None


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
    prepare_refusal: str = "",
    with_chain: bool = True,
) -> Iterator[Harness]:
    intent = an_intent(intent_id=INTENT_ID)
    intents = FakeIntents(intent)
    gate = FakeGate(a_determination(verdict, intent_id=INTENT_ID))
    executor = FakeExecutor(refusal=executor_refusal)
    chain = FakeChain(spent=spent_on_chain, prepare_refusal=prepare_refusal)
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
            chain=chain if with_chain else None,
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
    def test_dispatch_returns_201_the_order_and_the_hash_it_signed(self, harness: Harness) -> None:
        response = harness.client.post(f"/v1/intents/{INTENT_ID}/dispatch", headers=OWNER)

        assert response.status_code == 201, response.text
        body = response.json()
        order = harness.chain.prepared[0]
        assert body["intent_id"] == str(INTENT_ID)
        # The hash is the prepared one — signed, persisted, and only then broadcast (SC-3).
        assert body["tx_hash"] == a_hash(str(order.id))
        assert body["status"] == "submitted"
        assert body["nullifier"].startswith("0x")
        assert body["events"] == ["SettlementOrdered", "SettlementSubmitted"]
        # The service itself sends nothing: the bytes travel through the governed step (SC-2), so the
        # gateway's own `broadcast` is never called on this path.
        assert harness.chain.broadcast == []

    def test_the_order_is_persisted_and_readable_afterwards(self, harness: Harness) -> None:
        created = harness.client.post(f"/v1/intents/{INTENT_ID}/dispatch", headers=OWNER)
        order_id = created.json()["order_id"]

        read = harness.client.get(f"/v1/orders/{order_id}", headers=OWNER)

        assert read.status_code == 200
        assert read.json()["status"] == "submitted"
        assert read.json()["tx_hash"] == created.json()["tx_hash"]
        assert read.json()["amount_micro_usdc"] == 42_500_000

    def test_the_governed_step_runs_only_after_the_hash_is_persisted(
        self, harness: Harness
    ) -> None:
        """SC-3, the ordering itself: hash on the order, status still `signed`, then broadcast."""
        harness.client.post(f"/v1/intents/{INTENT_ID}/dispatch", headers=OWNER)

        order = harness.chain.prepared[0]
        assert harness.executor.seen == [
            (a_hash(str(order.id)), "signed", signed_bytes(str(order.id)))
        ]

    def test_all_three_ports_are_reached(self, harness: Harness) -> None:
        """SC-1 (gate), SC-2 (executor gets the order), SC-5 (on-chain nullifier read)."""
        created = harness.client.post(f"/v1/intents/{INTENT_ID}/dispatch", headers=OWNER)

        assert created.status_code == 201
        assert harness.gate.reads == 1
        assert len(harness.executor.orders) == 1
        order = harness.executor.orders[0]
        # The settlement command's identity is the frozen `payments.dispatch` (SC-2); what that
        # command *runs* is the broadcaster, and only its argument is this order's signed payload.
        assert order.command_ref == "payments.dispatch"
        # The command is rendered from the order, and its only argument is the signed payload (SC-2).
        assert order.command_params()["raw_transaction"] == signed_bytes(str(order.id))
        assert order.command_params()["amount_usdc"] == 42_500_000
        assert harness.chain.reads == [order.nullifier]
        assert len(harness.chain.prepared) == 1


class TestRefusedDispatch:
    def test_a_deny_determination_is_a_409_and_nothing_is_dispatched(self, tmp_path: Path) -> None:
        with build_harness(tmp_path, verdict=DeterminationVerdict.DENY) as harness:
            response = harness.client.post(f"/v1/intents/{INTENT_ID}/dispatch", headers=OWNER)

        assert response.status_code == 409
        envelope = response.json()["error"]
        assert envelope["code"] == "CONFLICT"
        assert "allowance" in envelope["message"]
        assert harness.executor.orders == []
        assert harness.chain.prepared == []

    def test_a_rigorix_refusal_keeps_the_persisted_hash_and_the_signed_state(
        self, tmp_path: Path
    ) -> None:
        """SC-3: the guarded step may refuse; the hash it did not use is still on the order."""
        with build_harness(tmp_path, executor_refusal=BOUNDARY_REFUSAL) as harness:
            response = harness.client.post(f"/v1/intents/{INTENT_ID}/dispatch", headers=OWNER)
            order = harness.chain.prepared[0]
            read = harness.client.get(f"/v1/orders/{order.id}", headers=OWNER)

        assert response.status_code == 409
        assert BOUNDARY_REFUSAL in response.json()["error"]["message"]
        assert len(harness.executor.orders) == 1
        # `signed` is a real state, not an error: the hash and the bytes are here, nothing was sent.
        assert read.json()["status"] == "signed"
        assert read.json()["tx_hash"] == a_hash(str(order.id))

    def test_a_refusal_at_signing_persists_nothing(self, tmp_path: Path) -> None:
        """SC-3: an order that could never be signed must not occupy the intent's dispatch slot."""
        with build_harness(
            tmp_path, prepare_refusal="This payment requires the owner's signature."
        ) as harness:
            response = harness.client.post(f"/v1/intents/{INTENT_ID}/dispatch", headers=OWNER)
            listed = harness.client.get("/v1/orders", headers=OWNER)

        assert response.status_code == 409
        assert "owner's signature" in response.json()["error"]["message"]
        assert listed.json()["count"] == 0
        # Signing was attempted and refused, so the order never reached a hash or a status.
        assert harness.chain.prepared[0].tx_hash is None
        assert harness.chain.prepared[0].status.value == "ordered"
        assert harness.executor.orders == []

    def test_a_dispatch_without_a_chain_gateway_is_a_named_refusal(self, tmp_path: Path) -> None:
        """No signer means nothing to broadcast: refuse loudly instead of running an empty step."""
        with build_harness(tmp_path, with_chain=False) as harness:
            response = harness.client.post(f"/v1/intents/{INTENT_ID}/dispatch", headers=OWNER)
            listed = harness.client.get("/v1/orders", headers=OWNER)

        assert response.status_code == 409
        assert "never broadcast" in response.json()["error"]["message"]
        assert listed.json()["count"] == 0
        assert harness.executor.orders == []

    def test_a_spent_on_chain_nullifier_refuses_before_the_command_runs(
        self, tmp_path: Path
    ) -> None:
        with build_harness(tmp_path, spent_on_chain=True) as harness:
            response = harness.client.post(f"/v1/intents/{INTENT_ID}/dispatch", headers=OWNER)

        assert response.status_code == 409
        assert "settled" in response.json()["error"]["message"]
        # SC-5: the governed command never ran — a replay produces no transaction at all.
        assert harness.executor.orders == []
        assert harness.chain.prepared == []

    def test_a_replayed_dispatch_is_a_duplicate_settlement_and_runs_once(
        self, harness: Harness
    ) -> None:
        first = harness.client.post(f"/v1/intents/{INTENT_ID}/dispatch", headers=OWNER)
        second = harness.client.post(f"/v1/intents/{INTENT_ID}/dispatch", headers=OWNER)

        assert first.status_code == 201
        assert second.status_code == 409
        assert len(harness.executor.orders) == 1
        # The second attempt did not even sign: a replay is refused before a nonce is taken (SC-3).
        assert len(harness.chain.prepared) == 1

    def test_dispatch_requires_a_settlement_scope(self, harness: Harness) -> None:
        response = harness.client.post(f"/v1/intents/{INTENT_ID}/dispatch")

        assert response.status_code == 401
