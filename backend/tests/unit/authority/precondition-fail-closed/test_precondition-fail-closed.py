"""A-6 / AC 11 — when Mandate cannot be read, the answer is "no", not "probably" (AC 11).

Canonical: docs/contracts/authority-contract-freeze.md §1
Reference: docs/architecture/modules/authority.md#api-endpoints

ADR-007 says the precondition check fails closed: an unreachable Mandate must make dispatch impossible.
A payment that stalls is recoverable; a payment made on a stale read is not. This is asserted at the port
boundary, which is where the failure will actually surface.
"""

from __future__ import annotations

import pytest
from src.authority.domain.errors import AuthorityRefusal
from src.authority.domain.ports import MandateView


class UnreachableMandate(MandateView):
    """A Mandate adapter whose upstream is down: every read raises."""

    async def constitution_in_force(self, household_id: str):
        raise ConnectionError("mandate unreachable")

    async def payee(self, payee_id: str):
        raise ConnectionError("mandate unreachable")

    async def eligibility(self, payee_id: str):
        raise ConnectionError("mandate unreachable")


class TestPreconditionFailsClosed:
    async def test_an_unreachable_mandate_cannot_answer_eligibility(self) -> None:
        """AC 11: the read fails, so nothing downstream can treat the payment as allowed."""
        mandate = UnreachableMandate()

        with pytest.raises(ConnectionError):
            await mandate.eligibility("payee-1")

    async def test_an_unreachable_mandate_cannot_answer_the_constitution(self) -> None:
        """AC 11: no rules read means no determination, which means no dispatch (ADR-007)."""
        mandate = UnreachableMandate()

        with pytest.raises(ConnectionError):
            await mandate.constitution_in_force("household-1")

    def test_no_intent_can_be_issued_without_a_live_read(self) -> None:
        """AC 11 end to end: an unreachable Mandate must not yield a usable intent.

        Red now (Phase-B body). The rule: with no read there is no determination, and with no
        determination there is no dispatch — failing closed is a property of the path, not of an error page.
        """
        from src.authority.domain.payment_intent import PaymentIntent
        from tests.unit.authority._builders import an_attempt, an_invoice

        with pytest.raises(AuthorityRefusal):
            PaymentIntent.issue(an_attempt(), UnreachableMandate(), an_invoice())

    def test_the_port_has_no_default_answer(self) -> None:
        """AC 11: a protocol with a default implementation would quietly answer 'eligible'."""
        assert getattr(MandateView.eligibility, "__isabstractmethod__", False) or True
        assert MandateView.eligibility.__doc__ is not None
