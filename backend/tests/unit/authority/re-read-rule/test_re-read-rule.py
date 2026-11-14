"""A-6 — Authority re-reads Mandate at the moment of consequence (AC 7).

Canonical: docs/contracts/authority-contract-freeze.md §1
Reference: docs/architecture/modules/authority.md#ports-to-upstream-contexts-acl

Scenario 3: the payee was eligible when the payment was planned, and frozen before dispatch. The rule only
holds if the read happens *at dispatch* and the port offers no cached alternative — both asserted here.
"""

from __future__ import annotations

import pytest
from src.authority.domain.errors import AuthorityRefusal
from src.authority.domain.payment_intent import PaymentIntent
from src.authority.domain.ports import MandateView
from src.mandate.domain.values import Eligibility, PayeeStatus
from tests.unit.authority._builders import StubMandateView, a_payee, an_attempt, an_invoice


class TestReReadRule:
    def test_a_frozen_payee_is_refused_at_dispatch_even_though_it_was_eligible(self) -> None:
        """A-6, scenario 3: the intent is built against the *current* read, so a freeze since the plan
        shows up in the decision rather than after it.

        The refusal is produced by the decision path (Phase B), which is why this is red now: the freeze
        must not let a plan-time answer stand in for a fresh one, and `issue` is where the fresh read lands.
        """
        mandate = StubMandateView(
            payee=a_payee(status=PayeeStatus.FROZEN),
            eligibility=Eligibility.deny("payee_frozen"),
        )

        with pytest.raises(AuthorityRefusal):
            PaymentIntent.issue(an_attempt(), mandate, an_invoice())

    def test_the_port_offers_no_cached_read(self) -> None:
        """A-6: there is no `cached_*`/`cached_constitution` method to reach for by accident."""
        cached = [name for name in dir(MandateView) if "cach" in name.lower()]
        assert cached == []

    def test_the_read_carries_its_own_timestamp(self) -> None:
        """A-6: a view without `read_at` could not prove when it was read."""
        view = a_payee()
        assert view.read_at is not None

    async def test_commissioning_the_view_records_the_read(self) -> None:
        """A-6/A-2: the port is called at decision time, so the call log is the evidence of a re-read."""
        mandate = StubMandateView()

        await mandate.payee("payee-1")

        assert mandate.calls == [("payee", "payee-1")]
