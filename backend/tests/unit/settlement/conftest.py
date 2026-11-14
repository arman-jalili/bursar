"""Fixtures shared by the Settlement suites.

Canonical: docs/contracts/settlement-contract-freeze.md §1
Reference: .pi/architecture/modules/settlement.md#aggregate-settlementorder

Everything here is a factory call into the frozen surface or plain construction of a frozen view. In
Phase A `SettlementOrder.order` raises `NotImplementedError`, which is why the suites are red: the
assertions are rules (SC-1 … SC-11), and red means those rules are not implemented yet.
"""

from __future__ import annotations

import pytest
from src.settlement.domain.settlement_order import SettlementOrder
from src.settlement.domain.values import ChainNetwork
from src.settlement.domain.views import DeterminationView, PaymentIntentView
from src.shared.domain.money import Money

from tests.unit.settlement._fixtures import a_determination, an_anvil_network, an_intent


@pytest.fixture
def intent() -> PaymentIntentView:
    """A signed intent — the only input from which an order may be built (SC-1)."""
    return an_intent()


@pytest.fixture
def determination(intent: PaymentIntentView) -> DeterminationView:
    return a_determination(intent_id=intent.intent_id)


@pytest.fixture
def network() -> ChainNetwork:
    return an_anvil_network()


@pytest.fixture
def signed_amount(intent: PaymentIntentView) -> Money:
    """The amount the owner signed — what `mark_submitted` must be compared against (SC-9)."""
    return intent.amount


@pytest.fixture
def order(intent: PaymentIntentView, network: ChainNetwork, determination: DeterminationView):
    """An order in `ORDERED` — the starting point for SC-2 … SC-9."""
    return SettlementOrder.order(intent, network, determination)
