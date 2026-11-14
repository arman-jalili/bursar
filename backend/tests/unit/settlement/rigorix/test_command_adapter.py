"""G-3 — `RigorixCommandAdapter` is a refusal-or-ack executor over the Rigorix host (SC-2).

Canonical: .pi/architecture/modules/settlement.md#ports-infrastructure-adapters
Reference: docs/contracts/settlement-contract-freeze.md §2.8

No test here reaches a server: the fake client has the same call surface as
`rigorix_verifier.client.Client` (`version`, `template_create`, `run`), which is the seam the adapter was
written against.

The rules under test:

* the command text is the module constant rendered from `order.command_params()` — never a caller's string
  (SC-2) — and it broadcasts the order's own signed bytes, signing nothing (SC-3);
* an order with no signed transaction is refused before the host is contacted: there is nothing to send;
* a `Completed` run is an ack carrying the execution id and the audit URI (the evidence link back to the
  governed execution);
* a `Failed` run is a refusal that carries the step's error **verbatim** — the `run_command` refusal a
  server without a declared sandbox returns is exactly this case;
* a timeout and a transport failure are refusals, never a silent success.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

import pytest
from rigorix_verifier.client import RpcError, TransportError
from src.settlement.domain.errors import SettlementRefusal
from src.settlement.domain.settlement_order import SettlementOrder
from src.settlement.domain.views import PaymentIntentView
from src.settlement.infrastructure.rigorix.command_adapter import (
    DISPATCH_COMMAND,
    RigorixCommandAdapter,
)
from src.shared.infrastructure.config import Settings, load_settings

from tests.unit.settlement._fixtures import a_determination, an_anvil_network, an_intent

BOUNDARY_REFUSAL = (
    "run_command refused: no execution boundary declared (RIGORIX_SANDBOX is unset); "
    "shell execution is disabled"
)


#: Stand-in for `eth_account`'s signed bytes: `0x`-prefixed hex, never a real transaction.
RAW_TRANSACTION = "0x02f8" + "ab" * 60
TX_HASH = "0x" + "cd" * 32


def an_order() -> SettlementOrder:
    intent: PaymentIntentView = an_intent()
    return SettlementOrder.order(
        intent, an_anvil_network(), a_determination(intent_id=intent.intent_id)
    )


def a_signed_order() -> SettlementOrder:
    """The order as the use case hands it to the executor: hash and signed bytes already persisted."""
    order = an_order()
    order.mark_signed(TX_HASH, RAW_TRANSACTION, order.amount)
    return order


class FakeRigorixClient:
    """The client slice the adapter uses, with the same three calls and no network."""

    def __init__(
        self,
        run_result: Mapping[str, object] | None = None,
        *,
        delay_seconds: float = 0.0,
        run_error: Exception | None = None,
    ) -> None:
        self.run_result = dict(run_result or _completed_result())
        self.delay_seconds = delay_seconds
        self.run_error = run_error
        self.version_calls = 0
        self.templates: list[dict[str, Any]] = []
        self.runs: list[dict[str, Any]] = []

    def version(self) -> Any:
        self.version_calls += 1
        return {"api_version": "v1.0", "server": "fake-rigorix"}

    def template_create(self, params: Any) -> Any:
        self.templates.append(dict(params))
        return {"name": params["name"], "path": "templates/fake.json", "status": "created"}

    def run(self, params: Any) -> Any:
        self.runs.append(dict(params))
        if self.run_error is not None:
            raise self.run_error
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        return dict(self.run_result)


def _completed_result() -> dict[str, object]:
    return {
        "execution_id": "",
        "status": "Completed",
        "duration_ms": 12,
        "steps": [
            {"step_name": "dispatch", "success": True, "duration_ms": 10, "output": {"ok": True}}
        ],
        "evidence": {"status": "complete"},
        "audit_uri": "rigorix://audit/fake-execution",
    }


def a_settings(*, timeout_seconds: float = 30.0) -> Settings:
    return load_settings(
        rigorix_run_template="bursar-test-dispatch",
        rigorix_base_url="http://127.0.0.1:3001",
        rigorix_rpc_timeout_seconds=timeout_seconds,
    )


class TestCompletedRun:
    async def test_a_completed_run_is_an_ack_with_the_execution_and_audit_uri(self) -> None:
        order = a_signed_order()
        client = FakeRigorixClient()
        adapter = RigorixCommandAdapter(a_settings(), client=client)  # type: ignore[arg-type]

        ack = await adapter.execute(order)

        assert ack.accepted is True
        assert ack.command_ref == order.command_ref == "payments.dispatch"
        # The execution id is the settlement order id: the audit trail and the order are one identity.
        assert ack.execution_id == str(order.id)
        assert ack.audit_uri == "rigorix://audit/fake-execution"
        assert client.runs == [
            {"template_name": "bursar-test-dispatch", "execution_id": str(order.id)}
        ]

    async def test_the_template_carries_the_generated_command_and_the_required_timestamps(
        self,
    ) -> None:
        """SC-2/SC-3: the command is the module constant rendered from the order — and nothing else."""
        order = a_signed_order()
        client = FakeRigorixClient()
        adapter = RigorixCommandAdapter(a_settings(), client=client)  # type: ignore[arg-type]

        await adapter.execute(order)

        created = client.templates[0]
        assert created["name"] == "bursar-test-dispatch"
        assert created["overwrite"] is True
        plan = created["plan"]
        assert plan["name"] == "bursar-test-dispatch"
        # The server requires both timestamps even though the SDK's schema does not list them.
        assert plan["created_at"].endswith("Z")
        assert plan["updated_at"].endswith("Z")
        step = plan["steps"][0]
        assert step["tool"] == "run_command"
        assert step["requires_approval"] is False
        command = step["parameters"]["command"]
        assert command == DISPATCH_COMMAND.format(**order.command_params())
        # The governed step broadcasts the order's own signed bytes, and signs nothing itself.
        assert command == f"payments.broadcast --raw-tx {RAW_TRANSACTION}"
        assert str(order.id) not in command  # the id travels as execution_id, not as an argument
        # No routing data: the payee, the amount and the nullifier are inside the signed bytes.
        assert order.payee_address.value not in command
        assert order.nullifier.value not in command

    async def test_an_unsigned_order_is_refused_before_the_host_is_contacted(self) -> None:
        """SC-3: there is nothing to broadcast, so the governed step must not run at all."""
        client = FakeRigorixClient()
        adapter = RigorixCommandAdapter(a_settings(), client=client)  # type: ignore[arg-type]

        with pytest.raises(SettlementRefusal) as refused:
            await adapter.execute(an_order())

        assert refused.value.details["reason"] == "unsigned_order"
        assert client.version_calls == 0
        assert client.templates == []
        assert client.runs == []

    async def test_the_protocol_version_is_negotiated_once(self) -> None:
        client = FakeRigorixClient()
        adapter = RigorixCommandAdapter(a_settings(), client=client)  # type: ignore[arg-type]

        await adapter.execute(a_signed_order())
        await adapter.execute(a_signed_order())

        assert client.version_calls == 1


class TestRefusals:
    async def test_a_failed_run_is_a_refusal_carrying_the_step_error_verbatim(self) -> None:
        """The sandbox-boundary refusal must surface in the host's own words, never swallowed."""
        client = FakeRigorixClient(
            {
                "execution_id": "",
                "status": "Failed",
                "duration_ms": 3,
                "steps": [
                    {
                        "step_name": "dispatch",
                        "success": False,
                        "duration_ms": 1,
                        "error": BOUNDARY_REFUSAL,
                    }
                ],
                "audit_uri": "rigorix://audit/failed-execution",
            }
        )
        adapter = RigorixCommandAdapter(a_settings(), client=client)  # type: ignore[arg-type]

        with pytest.raises(SettlementRefusal) as refused:
            await adapter.execute(a_signed_order())

        assert BOUNDARY_REFUSAL in str(refused.value)
        assert refused.value.details["status"] == "Failed"
        assert refused.value.details["audit_uri"] == "rigorix://audit/failed-execution"
        # A refusal is a documented conflict, never a 500.
        assert refused.value.http_status == 409

    async def test_a_timeout_is_a_refusal(self) -> None:
        client = FakeRigorixClient(delay_seconds=0.5)
        adapter = RigorixCommandAdapter(
            a_settings(timeout_seconds=0.05),
            client=client,  # type: ignore[arg-type]
        )

        with pytest.raises(SettlementRefusal) as refused:
            await adapter.execute(a_signed_order())

        assert "did not answer" in str(refused.value)
        assert refused.value.details["reason"] == "rigorix_timeout"

    async def test_a_transport_failure_is_a_refusal(self) -> None:
        client = FakeRigorixClient(run_error=TransportError("transport: HTTP 502"))
        adapter = RigorixCommandAdapter(a_settings(), client=client)  # type: ignore[arg-type]

        with pytest.raises(SettlementRefusal) as refused:
            await adapter.execute(a_signed_order())

        assert "transport: HTTP 502" in str(refused.value)
        assert refused.value.details["reason"] == "rigorix_transport"

    async def test_a_json_rpc_error_is_a_refusal(self) -> None:
        client = FakeRigorixClient(run_error=RpcError(-32000, "template not found"))
        adapter = RigorixCommandAdapter(a_settings(), client=client)  # type: ignore[arg-type]

        with pytest.raises(SettlementRefusal) as refused:
            await adapter.execute(a_signed_order())

        assert "template not found" in str(refused.value)

    async def test_a_non_object_answer_is_a_refusal(self) -> None:
        class MalformedClient(FakeRigorixClient):
            def run(self, params: Any) -> Any:
                return ["not", "an", "object"]

        adapter = RigorixCommandAdapter(  # type: ignore[arg-type]
            a_settings(), client=MalformedClient()
        )

        with pytest.raises(SettlementRefusal) as refused:
            await adapter.execute(a_signed_order())

        assert refused.value.details["reason"] == "malformed_result"
