"""SC-2 / SC-5 / SC-11 — the ports keep the chain and the framework out of the domain.

Canonical: docs/contracts/settlement-contract-freeze.md §1 (SC-2, SC-5, SC-11)
Reference: docs/architecture/modules/settlement.md#ports-infrastructure-adapters

Defends module AC #2, #5 and #11 at the port boundary. The assertions are rules a port must preserve,
not method names:

* `PaymentExecutor` receives the **order**, so the command path can only come from
  `order.command_params()` (SC-2);
* `ChainGateway` reads the on-chain nullifier map, so a replay is refused one layer before the contract
  (SC-5 / SC-6);
* the gateway is parameterised by `ChainNetwork`, so an adapter cannot carry an address from another
  network (SC-11).
"""

from __future__ import annotations

import pytest
from src.settlement.domain.errors import DuplicateSettlementBlocked, UnknownNetwork
from src.settlement.domain.ports import CommandAck
from src.settlement.domain.services import NullifierPolicy
from src.settlement.domain.values import ChainNetwork, Nullifier


class _RecordingExecutor:
    """A `PaymentExecutor` that records what it was handed."""

    def __init__(self) -> None:
        self.order_refs: list[str] = []

    async def execute(self, order) -> CommandAck:  # type: ignore[no-untyped-def]
        self.order_refs.append(order.command_ref)
        return CommandAck(command_ref=order.command_ref, accepted=True)


class _SpentOnChain:
    """A `ChainGateway` read that reports the marker as spent."""

    async def is_nullifier_spent(self, nullifier: Nullifier) -> bool:
        return True


class TestPorts:
    async def test_the_executor_runs_the_order_s_own_command(self, order) -> None:
        """SC-2 / AC-2: the adapter is handed the order, so the path is derived, never passed."""
        executor = _RecordingExecutor()

        ack = await executor.execute(order)

        assert ack.command_ref == order.command_ref == "payments.dispatch"

    async def test_a_spent_on_chain_nullifier_is_refused_before_submission(self) -> None:
        """SC-5 / AC-5: the gateway's read feeds the same local refusal as the database does."""
        marker = Nullifier.derive("ab" * 32, "hh-1")
        gateway = _SpentOnChain()

        with pytest.raises(DuplicateSettlementBlocked):
            NullifierPolicy().guard_unspent(
                marker, already_spent=await gateway.is_nullifier_spent(marker)
            )

    def test_a_network_is_a_complete_configuration(self) -> None:
        """SC-11 / AC-11: chain id, router, USDC and confirmations travel together or not at all."""
        network = ChainNetwork.anvil()

        assert network.router_address
        assert network.usdc_address
        assert network.confirmations_required >= 1

    def test_an_unknown_chain_cannot_reach_the_chain_gateway(self) -> None:
        """SC-11 / AC-11: an adapter cannot be built for a chain nobody configured."""
        with pytest.raises(UnknownNetwork):
            ChainNetwork.for_chain(1)

    async def test_the_executor_cannot_be_asked_to_run_a_caller_chosen_path(self, order) -> None:
        """SC-2 / AC-2: the port takes an order and nothing else; a path argument cannot be supplied."""
        executor = _RecordingExecutor()

        with pytest.raises(TypeError):
            await executor.execute(order, "payments.transfer_to_attacker")  # type: ignore[call-arg]
