"""SC-11 — Anvil and Base Sepolia use their own chain id, router and USDC.

Canonical: docs/contracts/settlement-contract-freeze.md §1 (SC-11)
Reference: .pi/architecture/modules/settlement.md#components-chainnetwork

Defends module AC #11: no hardcoded address leaks between networks. The network configuration is a value
object with all four fields bound together, and an unknown chain id is refused (`UnknownNetwork`) rather
than defaulted — a default is the hardcoded address the AC forbids.
"""

from __future__ import annotations

import pytest
from src.settlement.domain.errors import UnknownNetwork
from src.settlement.domain.values import ChainNetwork


class TestNetworkConfig:
    def test_anvil_and_sepolia_do_not_share_a_chain_id(self) -> None:
        """SC-11 / AC-11: the chain id is what stops an Anvil run signing a Sepolia transaction."""
        assert ChainNetwork.anvil().chain_id != ChainNetwork.base_sepolia().chain_id

    def test_anvil_and_sepolia_do_not_share_a_router_address(self) -> None:
        """SC-11 / AC-11: the one hardcoded address that matters — a leak here is Lock 3 gone."""
        assert ChainNetwork.anvil().router_address != ChainNetwork.base_sepolia().router_address

    def test_anvil_and_sepolia_do_not_share_a_usdc_address(self) -> None:
        """SC-11 / AC-11: USDC is per-network; a shared address would approve a token that is not there."""
        assert ChainNetwork.anvil().usdc_address != ChainNetwork.base_sepolia().usdc_address

    def test_each_network_carries_its_own_confirmation_requirement(self) -> None:
        """SC-11 / AC-11: finality is per network, so the count travels with the config (SC-7)."""
        assert ChainNetwork.anvil().confirmations_required >= 1
        assert ChainNetwork.base_sepolia().confirmations_required >= 1

    def test_an_unconfigured_chain_is_refused(self) -> None:
        """SC-11 / AC-11: chain 1 has no settlement config, and there is no fallback."""
        with pytest.raises(UnknownNetwork):
            ChainNetwork.for_chain(1)

    def test_a_known_chain_id_resolves_to_its_configuration(self) -> None:
        """SC-11 / AC-11: lookup must return the same configuration the named factory builds."""
        anvil = ChainNetwork.anvil()

        resolved = ChainNetwork.for_chain(anvil.chain_id)

        assert resolved.router_address == anvil.router_address
