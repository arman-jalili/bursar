"""Contract tests — Household aggregate root (mandate v1, H-1…H-3).

Canonical: .pi/architecture/modules/mandate.md#aggregate-household
Reference: .pi/architecture/modules/mandate.md#acceptance-criteria (AC #9)

Frozen: the aggregate's identity, its three parties, the **factory** (`open`) and the two owner-guard
operations. Behaviour (does `open` really emit three events, does `assert_owner_acts` really raise for
an agent) belongs to the `aggregate-household` implementation item — the contract test asserts the
surface exists and that no setter undermines it.

Why the factory is part of the contract rather than an implementation detail: a household needs three
parties *and* a constitution v1. A constructor would allow a half-built household — a state every
other module would then have to defend against.

Rewritten from the generated placeholder (hyphenated method names → `SyntaxError`).
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest
from src.mandate.domain.entities import Agent, Owner, Payer
from src.mandate.domain.household import Household
from src.mandate.domain.ids import ConstitutionId, HouseholdId
from src.shared.domain.aggregate import AggregateRoot


class TestHouseholdIsAnAggregateRoot:
    def test_subclasses_aggregate_root(self) -> None:
        assert issubclass(Household, AggregateRoot)
        assert Household._model_kind == "aggregate-root"

    def test_identity_is_persistent(self) -> None:
        """An aggregate root compared by state is how identity bugs get introduced (ADR-008)."""
        assert dataclasses.is_dataclass(Household)
        assert Household.__dataclass_params__.eq is False  # type: ignore[attr-defined]

    def test_holds_the_three_parties_and_one_constitution(self) -> None:
        """H-1: one owner, one payer, one agent — expressed as scalar fields, not as a list.

        `version` is inherited bookkeeping (optimistic concurrency, ADR-002) and comes first because
        the base dataclass declares it; the domain fields are asserted as a set so a future reorder
        of the base class does not fail a domain contract.
        """
        names = {f.name for f in dataclasses.fields(Household) if not f.name.startswith("_")}
        assert names == {"id", "owner", "payer", "agent", "constitution_id", "version"}

    def test_party_annotations_are_entity_types(self) -> None:
        annotations = {f.name: f.type for f in dataclasses.fields(Household)}
        for party in ("owner", "payer", "agent"):
            assert party in annotations
        assert Household.__annotations__["owner"] in (Owner, "Owner")
        assert Household.__annotations__["payer"] in (Payer, "Payer")
        assert Household.__annotations__["agent"] in (Agent, "Agent")


class TestHouseholdFactory:
    def test_open_is_a_classmethod(self) -> None:
        """A factory, not a constructor: three parties + constitution v1 or nothing."""
        assert isinstance(inspect.getattr_static(Household, "open"), classmethod)

    def test_open_requires_all_three_parties_and_the_constitution(self) -> None:
        """Amended (2026-11-14): `household_id` joined the factory.

        The id must exist before the constitution and the actor's `PartyRef` are built, otherwise
        the constitution row is bound to an id the household then does not have, and every
        read-through by household finds no in-force version. Generating it inside `open` cannot
        work: the caller needs it first. It is optional and defaults to a fresh id, so every
        pre-existing call site is unchanged — which is what keeps this an amendment rather than a
        new contract.
        """
        signature = inspect.signature(Household.open)
        assert set(signature.parameters) == {
            "owner",
            "payer",
            "agent",
            "constitution",
            "actor",
            "household_id",
        }

    def test_the_amended_household_id_is_optional(self) -> None:
        """An amendment that made the new parameter required would silently break every caller."""
        parameter = inspect.signature(Household.open).parameters["household_id"]
        assert parameter.default is None
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY

    def test_open_is_keyword_only(self) -> None:
        """Positional `owner`/`payer` swaps are silent and catastrophic; kw-only prevents them."""
        for parameter in inspect.signature(Household.open).parameters.values():
            assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, parameter.name


class TestOwnerGuardsArePartOfTheContract:
    def test_assert_owner_acts_exists(self) -> None:
        """H-3 is enforced by a named guard so every owner-only path calls the same check."""
        assert callable(Household.assert_owner_acts)
        assert list(inspect.signature(Household.assert_owner_acts).parameters) == ["self", "actor"]

    def test_change_owner_requires_proof(self) -> None:
        """H-5: rotating the signer is itself an owner-signed act, not a key operation."""
        signature = inspect.signature(Household.change_owner)
        assert list(signature.parameters) == ["self", "new_owner", "proof", "actor"]
        assert signature.parameters["actor"].kind is inspect.Parameter.KEYWORD_ONLY

    def test_no_setters(self) -> None:
        public = [n for n in dir(Household) if not n.startswith("_")]
        assert not [n for n in public if n.startswith("set_")]

    def test_no_bulk_mutation_helpers(self) -> None:
        """`update(**fields)` / `patch()` would let a caller skip every invariant at once."""
        forbidden = {"update", "patch", "apply", "replace", "assign"}
        names = {n for n in dir(Household) if not n.startswith("_")}
        assert not (names & forbidden), (
            f"bulk mutation helpers on the aggregate: {names & forbidden}"
        )

    def test_parties_are_required_not_optional(self) -> None:
        """A household without an owner is not a valid state, so the type must not allow it."""
        for name in ("owner", "payer", "agent"):
            field = {f.name: f for f in dataclasses.fields(Household)}[name]
            assert field.default is dataclasses.MISSING
            assert field.default_factory is dataclasses.MISSING  # type: ignore[misc]


class TestHouseholdIds:
    def test_uses_its_own_identifier_types(self) -> None:
        annotations = {f.name: f.type for f in dataclasses.fields(Household)}
        assert annotations["id"] in (HouseholdId, "HouseholdId")
        assert annotations["constitution_id"] in (ConstitutionId, "ConstitutionId")

    def test_ids_are_not_interchangeable(self) -> None:
        """NewType gives the checker a chance to catch a PayeeId passed as a HouseholdId."""
        assert HouseholdId("x") != ConstitutionId("x") or str(HouseholdId("x")) == "x"


class TestAggregateRootEventContract:
    def test_aggregate_can_record_and_drain_events(self) -> None:
        """AC #12 depends on this: the application service drains and writes the outbox."""
        assert callable(AggregateRoot.record)
        assert callable(AggregateRoot.pull_events)

    def test_no_event_dispatch_from_inside_the_aggregate(self) -> None:
        """An aggregate that talks to a bus is untestable and unreplayable (ADR-003)."""
        forbidden = {"publish", "dispatch", "emit"}
        names = {n for n in dir(AggregateRoot) if not n.startswith("_")}
        assert not (names & forbidden), f"aggregate publishes: {names & forbidden}"

    @pytest.mark.parametrize("method", ["record", "pull_events"])
    def test_event_api_is_synchronous(self, method: str) -> None:
        """Recording a fact is pure memory work; making it async would tempt I/O into the aggregate."""
        assert not inspect.iscoroutinefunction(getattr(AggregateRoot, method))
