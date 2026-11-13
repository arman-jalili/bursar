"""A-4 — `requires_owner_signature` is derived, never passed in (AC 3).

Canonical: docs/contracts/authority-contract-freeze.md §1
Reference: .pi/architecture/modules/authority.md#aggregate-paymentintent

If this were an argument, the caller (the agent) could pass `False` and waive its own escalation. Derived
from newness and threshold, the escalation is a property of the world rather than a request.
"""

from __future__ import annotations

from src.authority.domain.payment_intent import PaymentIntent
from src.mandate.domain.values import PayeeStatus
from tests.unit.authority._builders import StubMandateView, a_payee, an_attempt, an_invoice


class TestRequiresOwnerSignature:
    def test_a_new_payee_at_a_small_amount_still_escalates(self) -> None:
        """A-4: newness alone forces the signature — 5 USDC to a first-time payee is not auto-pay."""
        mandate = StubMandateView(payee=a_payee(status=PayeeStatus.NEW))

        intent = PaymentIntent.issue(an_attempt(), mandate, an_invoice(amount="5.00"))

        assert intent.requires_owner_signature is True

    def test_an_eligible_payee_above_the_threshold_escalates(self) -> None:
        """A-4: 320 USDC against a 25 USDC threshold escalates even for a trusted payee (AC 3)."""
        mandate = StubMandateView(payee=a_payee(status=PayeeStatus.ELIGIBLE))

        intent = PaymentIntent.issue(an_attempt(), mandate, an_invoice(amount="320.00"))

        assert intent.requires_owner_signature is True

    def test_an_eligible_payee_below_the_threshold_does_not_escalate(self) -> None:
        """A-4: 12 USDC to a trusted payee auto-pays — the product must stay usable."""
        mandate = StubMandateView(payee=a_payee(status=PayeeStatus.ELIGIBLE))

        intent = PaymentIntent.issue(an_attempt(), mandate, an_invoice(amount="12.00"))

        assert intent.requires_owner_signature is False

    def test_exactly_the_threshold_still_auto_pays(self) -> None:
        """A-4: `exceeded_by` is strict, so paying the limit itself is still automatic."""
        mandate = StubMandateView(payee=a_payee(status=PayeeStatus.ELIGIBLE))

        intent = PaymentIntent.issue(an_attempt(), mandate, an_invoice(amount="25.00"))

        assert intent.requires_owner_signature is False

    def test_the_intent_carries_the_constitution_version_it_was_judged_against(self) -> None:
        """A-4/A-6: the version on the intent is the one Mandate had in force at issue time."""
        intent = PaymentIntent.issue(an_attempt(), StubMandateView(), an_invoice())

        assert intent.constitution_version == 3
