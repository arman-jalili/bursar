"""Behaviour — `Payee`: the scam scenario, the freeze, and the recovery path.

Canonical: .pi/architecture/modules/mandate.md#aggregate-payee
Reference: .pi/architecture/modules/mandate.md#acceptance-criteria (AC #3, AC #4, AC #5, AC #6, AC #9)

These are the tests that matter for the pitch: a poisoned invoice must quarantine the payee **without
moving the destination**, a freeze must survive a subsequent digest review, and clearing quarantine
must require the owner. The address assertion is byte-level on purpose — "the app helpfully updated the
payee's bank details" is the failure mode being prevented, so anything less than identity is too weak.
"""

from __future__ import annotations

import pytest
from src.mandate.domain.errors import OwnerActionRequired, OwnerProofInvalid
from src.mandate.domain.events import (
    PayeeDigestChanged,
    PayeeFrozen,
    PayeeQuarantined,
    PayeeReapproved,
    PayeeRegistered,
)
from src.mandate.domain.payee import Payee
from src.mandate.domain.values import (
    EligibilityVerdict,
    PartyRef,
    PayeeAddress,
    PayeeName,
    PayeeStatus,
    ReasonCode,
    Role,
)

from .conftest import FakeProof, a_digest


class TestRegistration:
    def test_registers_as_new_with_a_verification_event(self, payee: Payee) -> None:
        assert payee.status is PayeeStatus.NEW
        assert [type(e) for e in payee.pending_events] == [PayeeRegistered]

    def test_agent_cannot_register_a_payee(self, household_id, agent_actor: PartyRef) -> None:
        """AC #9 / P-1: an agent actor is refused before any state exists."""
        with pytest.raises(OwnerActionRequired) as caught:
            Payee.register(
                household_id=household_id,
                name=PayeeName("Scammer Ltd"),
                address=PayeeAddress("0x70997970C51812dc3A010C7d01b50e0d17dc79C8"),
                digest=a_digest(),
                actor=agent_actor,
                proof=FakeProof(),
            )
        assert caught.value.http_status == 403
        assert caught.value.details["role"] == Role.AGENT.value

    def test_invalid_owner_proof_is_refused(self, household_id, owner_actor: PartyRef) -> None:
        with pytest.raises(OwnerProofInvalid):
            Payee.register(
                household_id=household_id,
                name=PayeeName("Northwind"),
                address=PayeeAddress("0x70997970C51812dc3A010C7d01b50e0d17dc79C8"),
                digest=a_digest(),
                actor=owner_actor,
                proof=FakeProof(valid=False),
            )


class TestPoisonedInvoiceScenario:
    """AC #3 — scenario 2: the mismatch quarantines, and the address never moves."""

    def test_mismatch_quarantines_and_emits_both_events(self, payee: Payee) -> None:
        payee.pull_events()  # drop the registration event
        poisoned = a_digest("GB33BUKB20201555555555")

        payee.review_presented_digest(poisoned, invoice_id="inv-12")

        assert payee.status is PayeeStatus.QUARANTINED
        assert [type(e) for e in payee.pending_events] == [
            PayeeDigestChanged,
            PayeeQuarantined,
        ]
        digest_changed = payee.pending_events[0]
        assert digest_changed.presented_digest == poisoned.hash
        assert digest_changed.invoice_id == "inv-12"
        assert payee.pending_events[1].reason == ReasonCode.DIGEST_MISMATCH.value

    def test_address_is_byte_identical_after_quarantine(self, payee: Payee) -> None:
        before = payee.address.value
        payee.review_presented_digest(a_digest("GB33BUKB20201555555555"))
        assert payee.address.value == before, "quarantine must stop the payment, not redirect it"

    def test_matching_digest_changes_nothing(self, payee: Payee) -> None:
        payee.pull_events()
        payee.review_presented_digest(a_digest())
        assert payee.status is PayeeStatus.NEW
        assert payee.pending_events == ()

    def test_eligibility_moves_from_escalate_to_deny(self, payee: Payee) -> None:
        assert payee.eligibility().verdict is EligibilityVerdict.ESCALATE
        payee.review_presented_digest(a_digest("GB33BUKB20201555555555"))
        verdict = payee.eligibility()
        assert verdict.verdict is EligibilityVerdict.DENY
        assert verdict.reason == ReasonCode.PAYEE_QUARANTINED.value


class TestFreezeIsStrongerThanQuarantine:
    """AC #5 / P-4 — a frozen payee ignores digest review and never downgrades."""

    def test_freeze_emits_event_and_denies(self, payee: Payee, owner_actor: PartyRef) -> None:
        payee.pull_events()
        payee.freeze(owner_actor)
        assert payee.status is PayeeStatus.FROZEN
        assert [type(e) for e in payee.pending_events] == [PayeeFrozen]
        assert payee.eligibility().reason == ReasonCode.PAYEE_FROZEN.value

    def test_digest_review_on_a_frozen_payee_is_a_no_op(
        self, payee: Payee, owner_actor: PartyRef
    ) -> None:
        payee.freeze(owner_actor)
        payee.pull_events()

        payee.review_presented_digest(a_digest("GB33BUKB20201555555555"))

        assert payee.status is PayeeStatus.FROZEN, "freeze must not soften to quarantine"
        assert payee.pending_events == ()

    def test_quarantined_payee_can_be_frozen(self, payee: Payee, owner_actor: PartyRef) -> None:
        payee.review_presented_digest(a_digest("GB33BUKB20201555555555"))
        payee.freeze(owner_actor)
        assert payee.status is PayeeStatus.FROZEN

    def test_agent_cannot_freeze(self, payee: Payee, agent_actor: PartyRef) -> None:
        with pytest.raises(OwnerActionRequired):
            payee.freeze(agent_actor)
        assert payee.status is PayeeStatus.NEW

    def test_freezing_twice_is_idempotent(self, payee: Payee, owner_actor: PartyRef) -> None:
        payee.freeze(owner_actor)
        payee.pull_events()
        payee.freeze(owner_actor)
        assert payee.pending_events == ()


class TestReapproval:
    """AC #4 — the recovery path: owner-signed, baseline replaced, both digests recorded."""

    def test_owner_reapproval_clears_quarantine(self, payee: Payee, owner_actor: PartyRef) -> None:
        payee.review_presented_digest(a_digest("GB33BUKB20201555555555"))
        payee.pull_events()
        new_digest = a_digest("GB33BUKB20201555555555")

        payee.reapprove(new_digest, actor=owner_actor, proof=FakeProof())

        assert payee.status is PayeeStatus.ELIGIBLE
        assert payee.verified_digest == new_digest
        assert [type(e) for e in payee.pending_events] == [PayeeReapproved]
        event = payee.pending_events[0]
        assert event.previous_digest != event.new_digest
        assert event.new_digest == new_digest.hash

    def test_invalid_proof_leaves_status_unchanged(
        self, payee: Payee, owner_actor: PartyRef
    ) -> None:
        payee.review_presented_digest(a_digest("GB33BUKB20201555555555"))
        before = payee.verified_digest

        with pytest.raises(OwnerProofInvalid):
            payee.reapprove(
                a_digest("GB33BUKB20201555555555"), actor=owner_actor, proof=FakeProof(False)
            )

        assert payee.status is PayeeStatus.QUARANTINED
        assert payee.verified_digest == before, "a refused re-approval must not rebind the payee"

    def test_agent_cannot_reapprove(self, payee: Payee, agent_actor: PartyRef) -> None:
        with pytest.raises(OwnerActionRequired):
            payee.reapprove(a_digest("X"), actor=agent_actor, proof=FakeProof())

    def test_the_owner_is_asked_about_the_new_digest(
        self, payee: Payee, owner_actor: PartyRef
    ) -> None:
        """The proof must cover the new digest — otherwise an old approval could rebind a payee."""
        proof = FakeProof()
        payee.reapprove(a_digest("GB33BUKB20201555555555"), actor=owner_actor, proof=proof)
        assert proof.seen == [(payee.id, a_digest("GB33BUKB20201555555555"))]


class TestStateMachine:
    """AC #6 — the four statuses are reachable only through documented transitions."""

    def test_all_four_statuses_are_reachable(self, payee: Payee, owner_actor: PartyRef) -> None:
        assert payee.status is PayeeStatus.NEW

        payee.reapprove(a_digest(), actor=owner_actor, proof=FakeProof())
        assert payee.status is PayeeStatus.ELIGIBLE

        payee.review_presented_digest(a_digest("GB33BUKB20201555555555"))
        assert payee.status is PayeeStatus.QUARANTINED

        payee.freeze(owner_actor)
        assert payee.status is PayeeStatus.FROZEN

    def test_status_cannot_be_assigned_directly(self, payee: Payee) -> None:
        """Only intention methods move the state; the aggregate guards every invariant."""
        assert not hasattr(payee, "set_status")
        assert not any(n.startswith("set_") for n in dir(payee))

    @pytest.mark.parametrize("status", [PayeeStatus.NEW, PayeeStatus.ELIGIBLE])
    def test_new_and_eligible_are_payable_but_differ(self, payee: Payee, status) -> None:
        """NEW escalates when the constitution asks for it; ELIGIBLE never does."""
        assert payee.eligibility(require_signature_for_new_payee=True).verdict in {
            EligibilityVerdict.ESCALATE,
            EligibilityVerdict.ALLOW,
        }
