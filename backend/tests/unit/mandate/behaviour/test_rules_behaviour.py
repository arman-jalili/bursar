"""Behaviour — `Constitution`, `Household` and the eligibility resolver (AC #2, #7, #8, #9, #11).

Canonical: .pi/architecture/modules/mandate.md#aggregate-constitution
Reference: .pi/architecture/modules/mandate.md#aggregate-household

The two aggregates here are the *rules* half of the domain: what the constitution says, who may change
it, and which party is even allowed to try. The tests read as the invariants they protect.
"""

from __future__ import annotations

import pytest
from src.mandate.domain.constitution import Constitution, ConstitutionVersion, VersionStatus
from src.mandate.domain.entities import Owner
from src.mandate.domain.errors import (
    ConstitutionCorrupted,
    OwnerActionRequired,
    OwnerProofInvalid,
    ThresholdExceedsCap,
)
from src.mandate.domain.events import (
    AgentAuthorised,
    CapChanged,
    ConstitutionVersionPublished,
    OwnerRegistered,
    PayerEnrolled,
    ThresholdChanged,
)
from src.mandate.domain.household import Household
from src.mandate.domain.services import PayeeEligibilityResolver
from src.mandate.domain.values import (
    Cap,
    DisplayName,
    EligibilityVerdict,
    EvmAddress,
    PartyRef,
    PayeeStatus,
    ReasonCode,
    Role,
    Threshold,
    usdc_to_micro,
)

from .conftest import FakeProof


def _cap(amount: str) -> Cap:
    return Cap(micro_usdc=usdc_to_micro(amount))


def _threshold(amount: str) -> Threshold:
    return Threshold(micro_usdc=usdc_to_micro(amount))


class TestConstitutionInitial:
    """AC #7 — v1 exists, is in force, and carries a content hash."""

    def test_initial_creates_exactly_one_in_force_version(self, constitution: Constitution) -> None:
        live = constitution.in_force
        assert live.number == 1
        assert live.status is VersionStatus.IN_FORCE
        assert len(constitution.versions()) == 1

    def test_content_hash_is_stable_and_version_specific(self, constitution: Constitution) -> None:
        first = constitution.in_force.content_hash
        same = Constitution.initial(
            constitution.household_id, _cap("150"), _threshold("25")
        ).in_force.content_hash
        assert first == same
        assert len(first) == 64

    def test_threshold_above_cap_is_refused_at_creation(self, household_id) -> None:
        with pytest.raises(ThresholdExceedsCap) as caught:
            Constitution.initial(household_id, _cap("100"), _threshold("300"))
        assert caught.value.details["threshold_usdc"] == str(usdc_to_micro("300"))


class TestConstitutionAppend:
    """AC #7 — owner-signed, one supersession, history still readable."""

    def test_append_supersedes_exactly_one_version(
        self, constitution: Constitution, owner_actor: PartyRef
    ) -> None:
        previous = constitution.in_force
        new_version = constitution.append(
            _cap("300"), _threshold("50"), True, owner_actor, FakeProof()
        )

        assert new_version.number == 2
        assert constitution.in_force is new_version
        assert previous.status is VersionStatus.SUPERSEDED
        assert len([v for v in constitution.versions() if v.status is VersionStatus.IN_FORCE]) == 1

    def test_old_version_stays_readable_by_number(
        self, constitution: Constitution, owner_actor: PartyRef
    ) -> None:
        constitution.append(_cap("300"), _threshold("50"), True, owner_actor, FakeProof())
        assert constitution.find_version(1).cap.micro_usdc == usdc_to_micro("150")
        assert constitution.find_version(2).cap.micro_usdc == usdc_to_micro("300")
        with pytest.raises(KeyError):
            constitution.find_version(99)

    def test_append_emits_publish_and_cap_threshold_events(
        self, constitution: Constitution, owner_actor: PartyRef
    ) -> None:
        constitution.pull_events()
        constitution.append(_cap("300"), _threshold("50"), True, owner_actor, FakeProof())
        assert [type(e) for e in constitution.pull_events()] == [
            ConstitutionVersionPublished,
            CapChanged,
            ThresholdChanged,
        ]

    def test_unchanged_rules_are_not_republished(
        self, constitution: Constitution, owner_actor: PartyRef
    ) -> None:
        with pytest.raises(OwnerProofInvalid, match="already in force"):
            constitution.append(_cap("150"), _threshold("25"), True, owner_actor, FakeProof())

    def test_threshold_above_cap_is_refused_at_append(
        self, constitution: Constitution, owner_actor: PartyRef
    ) -> None:
        with pytest.raises(ThresholdExceedsCap):
            constitution.append(_cap("100"), _threshold("300"), True, owner_actor, FakeProof())
        assert constitution.in_force.number == 1, "a refused append must not supersede anything"

    def test_agent_cannot_append(self, constitution: Constitution, agent_actor: PartyRef) -> None:
        """AC #9: the agent may not edit policy — refused as 403, not 409."""
        with pytest.raises(OwnerActionRequired) as caught:
            constitution.append(_cap("999"), _threshold("999"), True, agent_actor, FakeProof())
        assert caught.value.http_status == 403
        assert constitution.in_force.cap.micro_usdc == usdc_to_micro("150")

    def test_invalid_proof_does_not_supersede(
        self, constitution: Constitution, owner_actor: PartyRef
    ) -> None:
        with pytest.raises(OwnerProofInvalid):
            constitution.append(_cap("300"), _threshold("50"), True, owner_actor, FakeProof(False))
        assert constitution.in_force.number == 1

    def test_the_owner_signs_the_cap_and_threshold(self, constitution: Constitution) -> None:
        proof = FakeProof()
        constitution.append(_cap("300"), _threshold("50"), True, PartyRef(Role.OWNER, "o1"), proof)
        assert proof.seen == [(constitution.household_id, _cap("300"), _threshold("50"))]


class TestInForceIsGuarded:
    """AC #8 — 0 or 2 versions in force is corruption, not a preference."""

    def test_no_version_in_force_raises(self, constitution: Constitution) -> None:
        for version in constitution.versions():
            version.supersede()
        with pytest.raises(ConstitutionCorrupted) as caught:
            _ = constitution.in_force
        assert caught.value.details["in_force_count"] == "0"

    def test_two_versions_in_force_raises(self, constitution: Constitution) -> None:
        constitution._versions.append(
            ConstitutionVersion(
                number=2,
                cap=_cap("300"),
                threshold=_threshold("50"),
                require_signature_for_new_payee=True,
                content_hash="x" * 64,
            )
        )
        with pytest.raises(ConstitutionCorrupted) as caught:
            _ = constitution.in_force
        assert caught.value.details["in_force_count"] == "2"

    def test_superseding_twice_is_illegal(
        self, constitution: Constitution, owner_actor: PartyRef
    ) -> None:
        previous = constitution.in_force
        constitution.append(_cap("300"), _threshold("50"), True, owner_actor, FakeProof())
        with pytest.raises(ConstitutionCorrupted):
            previous.supersede()


class TestHousehold:
    """AC #9 — one owner, one payer, one agent, and only the owner may act."""

    def test_open_creates_the_household_and_three_party_events(
        self, owner: Owner, payer, agent, constitution: Constitution, owner_actor: PartyRef
    ) -> None:
        household = Household.open(
            owner=owner, payer=payer, agent=agent, constitution=constitution, actor=owner_actor
        )
        assert household.constitution_id == constitution.id
        assert [type(e) for e in household.pull_events()] == [
            OwnerRegistered,
            PayerEnrolled,
            AgentAuthorised,
        ]

    def test_agent_cannot_open_a_household(
        self, owner: Owner, payer, agent, constitution: Constitution, agent_actor: PartyRef
    ) -> None:
        with pytest.raises(OwnerActionRequired) as caught:
            Household.open(
                owner=owner, payer=payer, agent=agent, constitution=constitution, actor=agent_actor
            )
        assert caught.value.http_status == 403

    def test_change_owner_requires_the_outgoing_signature(
        self, owner: Owner, payer, agent, constitution: Constitution, owner_actor: PartyRef
    ) -> None:
        household = Household.open(
            owner=owner, payer=payer, agent=agent, constitution=constitution, actor=owner_actor
        )
        # An owner actor is scoped to its household: the mandate's id, not a pre-generated one.
        owner_actor = PartyRef(role=Role.OWNER, id="owner-1", household_id=household.id)
        replacement = Owner(
            id=owner.id,
            address=EvmAddress("0x70997970C51812dc3A010C7d01b50e0d17dc79C8"),
            name=DisplayName("Sam"),
        )

        with pytest.raises(OwnerProofInvalid):
            household.change_owner(replacement, FakeProof(False), actor=owner_actor)
        assert household.owner.address == owner.address

        household.change_owner(replacement, FakeProof(), actor=owner_actor)
        assert household.owner.address == replacement.address

    def test_agent_cannot_change_the_owner(
        self,
        owner: Owner,
        payer,
        agent,
        constitution: Constitution,
        owner_actor: PartyRef,
        agent_actor: PartyRef,
    ) -> None:
        household = Household.open(
            owner=owner, payer=payer, agent=agent, constitution=constitution, actor=owner_actor
        )
        with pytest.raises(OwnerActionRequired):
            household.change_owner(owner, FakeProof(), actor=agent_actor)

    def test_actor_from_another_household_is_refused(
        self, owner: Owner, payer, agent, constitution: Constitution, owner_actor: PartyRef
    ) -> None:
        """An owner of household A must not be able to act on household B."""
        household = Household.open(
            owner=owner, payer=payer, agent=agent, constitution=constitution, actor=owner_actor
        )
        foreign = PartyRef(role=Role.OWNER, id="o-other", household_id="some-other-household")
        with pytest.raises(OwnerActionRequired):
            household.assert_owner_acts(foreign)


class TestEligibilityResolver:
    """AC #11 — the derived verdict Authority consumes at dispatch."""

    @pytest.mark.parametrize(
        ("status", "verdict", "reason"),
        [
            (PayeeStatus.ELIGIBLE, EligibilityVerdict.ALLOW, None),
            (PayeeStatus.NEW, EligibilityVerdict.ESCALATE, ReasonCode.NEW_PAYEE.value),
            (
                PayeeStatus.QUARANTINED,
                EligibilityVerdict.DENY,
                ReasonCode.PAYEE_QUARANTINED.value,
            ),
            (PayeeStatus.FROZEN, EligibilityVerdict.DENY, ReasonCode.PAYEE_FROZEN.value),
        ],
    )
    def test_status_maps_to_the_documented_verdict(self, status, verdict, reason) -> None:
        resolved = PayeeEligibilityResolver().resolve(status)
        assert resolved.verdict is verdict
        assert resolved.reason == reason

    def test_constitution_flag_can_auto_pay_a_new_payee(self) -> None:
        resolved = PayeeEligibilityResolver().resolve(
            PayeeStatus.NEW, require_signature_for_new_payee=False
        )
        assert resolved.verdict is EligibilityVerdict.ALLOW

    def test_the_flag_never_softens_a_denial(self) -> None:
        """A permissive constitution cannot make a frozen payee payable."""
        for flag in (True, False):
            assert (
                PayeeEligibilityResolver()
                .resolve(PayeeStatus.FROZEN, require_signature_for_new_payee=flag)
                .is_denied
            )
