"""Fixtures for the chain suite: a compiled contract, a local EVM, and a gateway on top of it.

Canonical: `docs/contracts/settlement-contract-freeze.md` §1 (SC-5, SC-6, SC-7, SC-11)
Reference: `docs/architecture/modules/settlement.md#ports-infrastructure-adapters`

No anvil, no network: `py-solc-x` compiles `contracts/src` and `eth-tester` runs the bytecode in
process. The `ChainNetwork` and `Settings` fixtures are built from the *deployed* addresses, so a test
cannot accidentally point the gateway at a hardcoded router from another chain (that is SC-11's leak,
and `test_a_network_from_another_chain_is_refused` pins the refusal).
"""

from __future__ import annotations

import pytest
from src.settlement.domain.values import ChainNetwork
from src.settlement.infrastructure.chain.web3_gateway import Web3ChainGateway
from src.shared.infrastructure.config import Settings, load_settings

from tests.unit.settlement.chain._evm import LocalChain, deploy_local_chain


@pytest.fixture
def chain() -> LocalChain:
    """A fresh py-evm chain with `PaymentRouter` + `TestUsdc` deployed and the operator funded."""
    return deploy_local_chain()


@pytest.fixture
def chain_network(chain: LocalChain) -> ChainNetwork:
    """The network value the order will be bound to — this chain's id, router and token (SC-11)."""
    return ChainNetwork(
        chain_id=chain.w3.eth.chain_id,
        router_address=chain.router.address,
        usdc_address=chain.usdc.address,
        confirmations_required=1,
    )


@pytest.fixture
def chain_settings(chain: LocalChain) -> Settings:
    """Settings for the deployed chain, with the operator's key as the settlement signer."""
    return load_settings(
        settlement_private_key=chain.operator_key.hex(),
        payment_router_address=chain.router.address,
        usdc_address=chain.usdc.address,
        chain_id=chain.w3.eth.chain_id,
        owner_address=chain.owner,
        confirmations_required=1,
        rpc_url="http://127.0.0.1:8545",
    )


@pytest.fixture
def gateway(
    chain: LocalChain, chain_network: ChainNetwork, chain_settings: Settings
) -> Web3ChainGateway:
    """The adapter under test: the provider is injected, which is the whole point of the constructor."""
    return Web3ChainGateway(chain.w3, chain_network, chain_settings)
