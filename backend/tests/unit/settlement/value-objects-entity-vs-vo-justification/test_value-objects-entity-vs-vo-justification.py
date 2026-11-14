"""SC-11 — the value objects are values: equal by content, validated, immutable.

Canonical: docs/contracts/settlement-contract-freeze.md §1 (SC-11)
Reference: docs/architecture/modules/settlement.md#value-objects-entity-vs-vo-justification

Defends the entity-vs-VO decision behind module AC #11 and SC-5:

* a `Nullifier`'s only property is that it can be spent once — two equal values **are** the same marker,
  so equality by content is the duplicate rule (not an entity with an identity of its own);
* `ChainNetwork` is a configuration value: two networks that differ only in their confirmation count are
  different network policies, not the same network at two moments;
* `PayeeAddress` is Mandate's value object, and it refuses a malformed address at construction — the
  destination is validated by the context that owns it (conformist), not by Settlement.
"""

from __future__ import annotations

import pytest
from src.mandate.domain.errors import InvalidValue
from src.mandate.domain.values import PayeeAddress
from src.settlement.domain.values import ChainNetwork, Nullifier


class TestNullifierIsAValue:
    def test_two_equal_values_are_the_same_marker(self) -> None:
        """SC-5: equality by content is the duplicate rule — nothing else distinguishes two markers."""
        first = Nullifier.derive("ab" * 32, "hh-1")
        second = Nullifier.derive("ab" * 32, "hh-1")

        assert first.same_as(second)

    def test_a_different_value_is_a_different_marker(self) -> None:
        """SC-5: a different invoice hash must not collide with another invoice's marker."""
        one = Nullifier.derive("ab" * 32, "hh-1")
        other = Nullifier.derive("ab" * 32, "hh-2")

        assert not one.same_as(other)

    def test_a_marker_cannot_be_mutated_after_construction(self) -> None:
        """SC-5: a marker that can be edited is a marker that can be re-spent."""
        marker = Nullifier.derive("ab" * 32, "hh-1")

        with pytest.raises((AttributeError, TypeError)):
            marker.value = "0x" + "cd" * 32  # type: ignore[misc]

        assert marker.value.startswith("0x")


class TestChainNetworkIsAConfigurationValue:
    def test_two_configs_that_differ_only_in_confirmations_are_different_policies(self) -> None:
        """SC-11: finality is part of the network policy, so the confirmation count is part of the value."""
        network = ChainNetwork.anvil()
        deeper = ChainNetwork(
            chain_id=network.chain_id,
            router_address=network.router_address,
            usdc_address=network.usdc_address,
            confirmations_required=network.confirmations_required + 1,
        )

        assert network != deeper

    def test_a_config_cannot_be_mutated_after_construction(self) -> None:
        """SC-11: a network that can change under a running order is a hardcoded address in disguise."""
        network = ChainNetwork.anvil()

        with pytest.raises((AttributeError, TypeError)):
            network.confirmations_required = 0  # type: ignore[misc]

        assert network.confirmations_required >= 1


class TestPayeeAddressBelongsToMandate:
    def test_a_malformed_payee_address_is_refused_at_construction(self) -> None:
        """SC-2: the destination is validated where it is owned, before Settlement ever sees it."""
        with pytest.raises(InvalidValue):
            PayeeAddress("not-an-evm-address")

    def test_a_checksummed_address_is_accepted(self) -> None:
        """SC-2: the honest address — the one Mandate puts on the intent — must construct."""
        address = PayeeAddress("0x70997970C51812dc3A010C7d01b50e0d17dc79C8")

        assert address.value.endswith("d17dc79C8")
