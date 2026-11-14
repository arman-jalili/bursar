"""A-2 — the ACL types expose no routing fields, so a proposal cannot smuggle one.

Canonical: docs/contracts/authority-contract-freeze.md §1
Reference: docs/architecture/modules/authority.md#ports-to-upstream-contexts-acl

The strongest version of A-2 is structural: `AttemptView` has no `payee_address`, no `bank_digest` and no
`command`, so `PaymentIntent.issue` has nowhere to read them from. This file asserts that absence as a rule,
plus the read-through requirement on the Mandate side (A-6).
"""

from __future__ import annotations

from dataclasses import fields

from src.authority.domain.ports import (
    AttemptView,
    ConstitutionView,
    InvoiceView,
    MandateView,
    PayeeView,
)

FORBIDDEN = {"payee_address", "bank_digest", "command", "command_path", "cap", "threshold"}


class TestAttemptViewIsAnAcl:
    def test_the_attempt_view_carries_no_routing_field(self) -> None:
        """A-2: nothing to inject — the type cannot express a destination."""
        names = {field.name for field in fields(AttemptView)}
        assert not (names & FORBIDDEN), names & FORBIDDEN

    def test_the_invoice_view_carries_no_routing_field(self) -> None:
        """A-2: the invoice contributes an amount and an id, never a destination."""
        names = {field.name for field in fields(InvoiceView)}
        assert not (names & FORBIDDEN), names & FORBIDDEN

    def test_the_payee_view_is_the_only_source_of_a_destination(self) -> None:
        """A-2: `PayeeView.address` exists precisely so Mandate is the single origin of routing."""
        names = {field.name for field in fields(PayeeView)}
        assert "address" in names
        assert "digest" in names


class TestTheAclHoldsUnderUse:
    def test_an_attempt_cannot_dictate_the_destination_through_the_port(self) -> None:
        """A-2 end to end: issue() is fed views, so the only address available is Mandate's.

        Red now: `issue` is a Phase-B body. The rule it will defend is that the ACL — not the caller —
        decides what a payment is pointed at.
        """
        from src.authority.domain.payment_intent import PaymentIntent
        from tests.unit.authority._builders import StubMandateView, an_attempt, an_invoice

        intent = PaymentIntent.issue(an_attempt(), StubMandateView(), an_invoice())

        assert intent.payee_address == StubMandateView()._payee.address


class TestMandateViewIsReadThrough:
    def test_the_port_exposes_no_cached_variant(self) -> None:
        """A-6: no `cached_*` shortcut, so a plan-time answer cannot be substituted for a fresh one."""
        assert [n for n in dir(MandateView) if "cach" in n.lower()] == []

    def test_the_constitution_view_stamps_the_read(self) -> None:
        """A-6: a view without `read_at` could not prove when it was consulted."""
        names = {field.name for field in fields(ConstitutionView)}
        assert "read_at" in names
        assert "version" in names
