"""SC-1 — an order is creatable only from a determination that permits dispatch.

Canonical: docs/contracts/settlement-contract-freeze.md §1 (SC-1)
Reference: .pi/architecture/modules/settlement.md#aggregate-settlementorder

Defends module AC #1: without an allow/approved determination the factory raises
`DispatchWithoutAuthority` and no order exists — nothing is persisted. The rule lives in
`DeterminationView.permits_dispatch`, so every caller asks the same question instead of comparing
verdict strings in three places.
"""

from __future__ import annotations

import pytest
from src.authority.domain.values import DeterminationVerdict
from src.settlement.domain.errors import DispatchWithoutAuthority
from src.settlement.domain.settlement_order import SettlementOrder
from src.settlement.domain.values import SettlementStatus
from src.settlement.domain.views import DeterminationView

from tests.unit.settlement._fixtures import a_determination


class TestOrderRequiresAuthority:
    def test_a_denied_determination_cannot_become_an_order(self, intent, network) -> None:
        """SC-1 / AC-1: a DENY must raise, and the caller gets no order to persist."""
        denial = a_determination(DeterminationVerdict.DENY, intent_id=intent.intent_id)

        with pytest.raises(DispatchWithoutAuthority):
            SettlementOrder.order(intent, network, denial)

    def test_an_escalation_without_an_approval_cannot_become_an_order(
        self, intent, network
    ) -> None:
        """SC-1 / AC-1: an escalation is a question, not a permission, until the owner approves."""
        pending_approval = a_determination(
            DeterminationVerdict.ESCALATE, intent_id=intent.intent_id, approval_granted=False
        )

        with pytest.raises(DispatchWithoutAuthority):
            SettlementOrder.order(intent, network, pending_approval)

    def test_an_allow_determination_produces_an_ordered_order(self, intent, network) -> None:
        """SC-1 / AC-1: the honest case must pass — an allow is the normal path."""
        allow = a_determination(DeterminationVerdict.ALLOW, intent_id=intent.intent_id)

        order = SettlementOrder.order(intent, network, allow)

        assert order.status is SettlementStatus.ORDERED

    def test_an_escalation_that_became_an_approval_may_dispatch(self, intent, network) -> None:
        """SC-1 / AC-1: `escalate` + `ApprovalGranted` is the second legal permission."""
        granted = a_determination(
            DeterminationVerdict.ESCALATE, intent_id=intent.intent_id, approval_granted=True
        )

        order = SettlementOrder.order(intent, network, granted)

        assert order.status is SettlementStatus.ORDERED

    @pytest.mark.parametrize(
        ("verdict", "approval_granted", "permits"),
        [
            (DeterminationVerdict.ALLOW, False, True),
            (DeterminationVerdict.DENY, False, False),
            (DeterminationVerdict.ESCALATE, False, False),
            (DeterminationVerdict.ESCALATE, True, True),
        ],
    )
    def test_permits_dispatch_is_the_single_authority_question(
        self,
        verdict: DeterminationVerdict,
        approval_granted: bool,
        permits: bool,
        intent,
    ) -> None:
        """SC-1 / AC-1: one predicate decides; a caller cannot invent a fifth answer."""
        view = DeterminationView(
            intent_id=intent.intent_id, verdict=verdict, approval_granted=approval_granted
        )

        assert view.permits_dispatch() is permits
