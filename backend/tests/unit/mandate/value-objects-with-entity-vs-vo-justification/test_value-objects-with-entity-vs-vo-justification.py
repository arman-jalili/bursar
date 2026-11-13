"""Contract tests — value objects and the entity-vs-VO line (mandate v1).

Canonical: .pi/architecture/modules/mandate.md#value-objects-with-entity-vs-vo-justification
Reference: .pi/architecture/decisions/ADR-008-proportional-modeling-depth.md

What is frozen here is the *modelling decision*, not the behaviour: which types are value objects
(immutable, equal by value, no identity), which are entities (equality by identity), and which are
closed enumerations. This is the one contract that, if it drifts, silently turns the model anemic —
a `PayeeStatus` that becomes a plain `str`, or a `Cap` that gains an `id`, would pass every
behavioural test and still be wrong.

Rewritten from the generated placeholder (hyphenated method names → `SyntaxError`).
"""

from __future__ import annotations

import dataclasses
import enum
import inspect

import pytest
from src.mandate.domain.entities import Agent, Owner, Payer
from src.mandate.domain.values import (
    BankDigest,
    Cap,
    DisplayName,
    Eligibility,
    EligibilityVerdict,
    EvmAddress,
    PartyRef,
    PayeeAddress,
    PayeeName,
    PayeeStatus,
    Role,
    RoutingDetails,
    Threshold,
)
from src.shared.domain.value_object import ValueObject

VALUE_OBJECTS = [
    BankDigest,
    Cap,
    Threshold,
    PartyRef,
    EvmAddress,
    PayeeAddress,
    DisplayName,
    PayeeName,
    RoutingDetails,
    Eligibility,
]


#: Value objects that legitimately carry an `id` field because it references *another* object's
#: identity. `PartyRef` is the actor of an event: `(role, id)` pointing at an `Owner`/`Payer`/`Agent`.
REFERENCE_VALUE_OBJECTS = {PartyRef}


@pytest.mark.parametrize("vo", VALUE_OBJECTS)
class TestEveryValueObject:
    def test_subclasses_value_object(self, vo: type) -> None:
        assert issubclass(vo, ValueObject), f"{vo.__name__} must be a ValueObject"

    def test_marked_as_value_object_not_entity(self, vo: type) -> None:
        """The marker is what architecture tests and reviewers read instead of prose."""
        assert vo._vo_kind == "value-object"

    def test_is_a_frozen_dataclass(self, vo: type) -> None:
        assert dataclasses.is_dataclass(vo)
        assert vo.__dataclass_params__.frozen is True, f"{vo.__name__} must be immutable"

    def test_has_no_identity_field(self, vo: type) -> None:
        """An `id` on a value object is the classic modelling error this file exists to catch.

        Exception: a *reference* value object carries another object's identity on purpose
        (`PartyRef`). The distinction is auditable rather than assumed, hence the explicit set.
        """
        if vo in REFERENCE_VALUE_OBJECTS:
            pytest.skip(f"{vo.__name__} references an identity rather than owning one")
        names = {f.name for f in dataclasses.fields(vo)}
        assert "id" not in names, f"{vo.__name__} is a value object and must not carry identity"

    def test_is_hashable(self, vo: type) -> None:
        """Value objects get used as dict keys / set members (digests, caps, statuses)."""
        assert vo.__hash__ is not None


class TestPartyRefIsAReference:
    """`PartyRef(role, id)` attributes an action; the `id` is a pointer, not an identity.

    Freezing the distinction matters: if `PartyRef` ever gained mutable state or stopped comparing by
    value, event attribution would become ambiguous — two refs to the same owner would stop being
    equal, and a permission check based on one would not recognise the other.
    """

    def test_equality_is_by_role_and_target(self) -> None:
        assert PartyRef(role=Role.OWNER, id="o1") == PartyRef(role=Role.OWNER, id="o1")
        assert PartyRef(role=Role.OWNER, id="o1") != PartyRef(role=Role.OWNER, id="o2")
        assert PartyRef(role=Role.OWNER, id="o1") != PartyRef(role=Role.AGENT, id="o1")

    def test_carries_no_mutable_state(self) -> None:
        names = {f.name for f in dataclasses.fields(PartyRef)}
        assert names == {"role", "id", "household_id"}

    def test_agent_role_is_representable_so_it_can_be_refused(self) -> None:
        """H-3 is only enforceable if an agent actor can be expressed and then rejected."""
        assert PartyRef(role=Role.AGENT, id="a1").role is Role.AGENT


class TestPayeeStatus:
    def test_is_a_closed_enumeration(self) -> None:
        assert issubclass(PayeeStatus, enum.StrEnum)
        assert {s.value for s in PayeeStatus} == {"new", "eligible", "quarantined", "frozen"}

    def test_members_are_wire_stable(self) -> None:
        """These strings appear in evidence payloads and console copy tables."""
        assert PayeeStatus.NEW.value == "new"
        assert PayeeStatus.QUARANTINED.value == "quarantined"
        assert PayeeStatus.FROZEN.value == "frozen"


class TestRole:
    def test_three_roles_only(self) -> None:
        assert {r.value for r in Role} == {"owner", "payer", "agent"}

    def test_role_is_not_a_free_string(self) -> None:
        """H-3 (`only the owner may change rules`) relies on a closed role set."""
        assert issubclass(Role, enum.StrEnum)


class TestEligibility:
    def test_three_verdicts(self) -> None:
        assert {v.value for v in EligibilityVerdict} == {"allow", "escalate", "deny"}

    def test_factories_produce_the_three_shapes(self) -> None:
        assert Eligibility.allow().verdict is EligibilityVerdict.ALLOW
        escalated = Eligibility.escalate("new_payee")
        assert escalated.verdict is EligibilityVerdict.ESCALATE
        assert escalated.reason == "new_payee"
        denied = Eligibility.deny("payee_frozen")
        assert denied.is_denied and denied.reason == "payee_frozen"

    def test_allow_is_the_only_allowed_verdict(self) -> None:
        assert Eligibility.allow().is_allowed
        assert not Eligibility.deny("x").is_allowed
        assert not Eligibility.escalate("new_payee").is_allowed


class TestEntitiesAreNotValueObjects:
    """The other half of the justification: the parties persist and are equal by identity."""

    @pytest.mark.parametrize("entity", [Owner, Payer, Agent])
    def test_is_not_a_value_object(self, entity: type) -> None:
        assert not issubclass(entity, ValueObject)

    @pytest.mark.parametrize("entity", [Owner, Payer, Agent])
    def test_equality_is_by_identity(self, entity: type) -> None:
        params = entity.__dataclass_params__  # type: ignore[attr-defined]
        assert params.eq is False, (
            f"{entity.__name__} must not compare by state: two owners with identical fields are "
            "still two owners (ADR-008)"
        )

    def test_no_setters_on_entities(self) -> None:
        """State changes go through the aggregate's intention methods, never a setter."""
        for entity in (Owner, Payer, Agent):
            public = [n for n in dir(entity) if not n.startswith("_")]
            assert not [n for n in public if n.startswith("set_")], entity.__name__


class TestNoBehaviourLeakedIntoFreeze:
    """The frozen contract exposes shape; behaviour bodies land with the implementation items."""

    def test_bank_digest_hashing_is_not_yet_implemented(self) -> None:
        with pytest.raises(NotImplementedError):
            BankDigest.from_routing_details(RoutingDetails(scheme="sepa", account_number="1"))

    def test_cap_comparison_is_not_yet_implemented(self) -> None:
        with pytest.raises(NotImplementedError):
            Cap(micro_usdc=10).at_least(5)

    def test_payee_status_has_no_transition_methods(self) -> None:
        """Transitions belong to `Payee`, not to the enum — the aggregate guards the invariants."""
        assert not [m for m in dir(PayeeStatus) if m.startswith("to_")]
        assert not inspect.isfunction(PayeeStatus.NEW)
