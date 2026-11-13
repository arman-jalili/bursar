"""Contract tests — Constitution aggregate root (mandate v1, H-4…H-8).

Canonical: .pi/architecture/modules/mandate.md#aggregate-constitution
Reference: .pi/architecture/decisions/ADR-007-compliance-engine-architecture.md

Frozen here: the append-only lineage (`Constitution` + `ConstitutionVersion`), the one-way status
transition, the historical lookup, and the fact that `in_force` is a *derived* single answer rather
than a stored flag. Behaviour (supersession semantics, contiguity, content hashing, the
`ThresholdExceedsCap` raise) is the `aggregate-constitution` implementation item's job.

Two contract decisions worth defending:

* `ConstitutionVersion` is an **entity** (addressed by `(constitution_id, number)`, cited by past
  determinations), not a value object — so it is not frozen, and its only mutation is `supersede()`.
* `in_force` is a **property**, not a getter method, and it is the single place H-4 can fail loudly.
  Authority reads it at dispatch; a cached or defaulted answer is scenario 3's bug.

Rewritten from the generated placeholder (hyphenated method names → `SyntaxError`).
"""

from __future__ import annotations

import dataclasses
import enum
import inspect

from src.mandate.domain.constitution import (
    Constitution,
    ConstitutionPolicy,
    ConstitutionVersion,
    VersionStatus,
)
from src.mandate.domain.errors import ConstitutionCorrupted
from src.mandate.domain.values import Cap, Threshold
from src.shared.domain.aggregate import AggregateRoot
from src.shared.domain.value_object import ValueObject


class TestConstitutionIsAnAggregateRoot:
    def test_subclasses_aggregate_root(self) -> None:
        assert issubclass(Constitution, AggregateRoot)
        assert Constitution._model_kind == "aggregate-root"

    def test_holds_an_append_only_lineage(self) -> None:
        names = [f.name for f in dataclasses.fields(Constitution)]
        assert "_versions" in names, "history must be private; the public surface is read-only"

    def test_exposes_no_setter(self) -> None:
        public = [n for n in dir(Constitution) if not n.startswith("_")]
        assert not [n for n in public if n.startswith("set_")]

    def test_initial_is_the_only_entry_point_for_v1(self) -> None:
        assert isinstance(inspect.getattr_static(Constitution, "initial"), classmethod)
        assert list(inspect.signature(Constitution.initial).parameters) == [
            "household_id",
            "cap",
            "threshold",
            "require_signature_for_new_payee",
        ]


class TestConstitutionVersionIsAnEntity:
    def test_is_not_a_value_object(self) -> None:
        """Versions have identity (number) and a lifecycle; equality must not be structural."""
        assert not issubclass(ConstitutionVersion, ValueObject)

    def test_equality_is_by_identity(self) -> None:
        assert ConstitutionVersion.__dataclass_params__.eq is False  # type: ignore[attr-defined]

    def test_holds_exactly_what_the_enforcement_engine_reads(self) -> None:
        """ADR-007 Lock 2 reads these fields at dispatch; anything extra would drift."""
        names = [f.name for f in dataclasses.fields(ConstitutionVersion)]
        assert names == [
            "number",
            "cap",
            "threshold",
            "require_signature_for_new_payee",
            "content_hash",
            "status",
        ]

    def test_cap_and_threshold_are_value_objects(self) -> None:
        annotations = ConstitutionVersion.__annotations__
        assert annotations["cap"] in (Cap, "Cap")
        assert annotations["threshold"] in (Threshold, "Threshold")

    def test_status_starts_in_force(self) -> None:
        assert ConstitutionVersion.__dataclass_fields__["status"].default is VersionStatus.IN_FORCE

    def test_only_two_statuses_exist(self) -> None:
        """H-7: a version is either binding or history. No draft, no archived, no deleted."""
        assert issubclass(VersionStatus, enum.StrEnum)
        assert {s.value for s in VersionStatus} == {"in_force", "superseded"}

    def test_supersede_is_the_only_mutation(self) -> None:
        mutators = [
            n
            for n, m in inspect.getmembers(ConstitutionVersion, predicate=inspect.isfunction)
            if not n.startswith("_") and n not in {"supersede", "next_version"}
        ]
        assert mutators == [], f"unexpected behaviour on an immutable version: {mutators}"

    def test_next_version_is_a_factory(self) -> None:
        """H-8: contiguity and a fresh content hash are the factory's job, not the caller's."""
        assert callable(ConstitutionVersion.next_version)
        assert list(inspect.signature(ConstitutionVersion.next_version).parameters) == [
            "self",
            "cap",
            "threshold",
            "require_signature_for_new_payee",
        ]


class TestInForceIsDerivedNotStored:
    def test_in_force_is_a_property(self) -> None:
        """A stored flag could contradict the lineage; a derived one cannot (H-4)."""
        assert isinstance(inspect.getattr_static(Constitution, "in_force"), property)

    def test_in_force_can_report_corruption(self) -> None:
        error = ConstitutionCorrupted(0)
        assert str(error.wire_message).startswith("Expected exactly one constitution version")
        assert error.details["in_force_count"] == "0"
        assert error.http_status == 500, (
            "corruption is a server fault, not a refusal: a refusal is an expected outcome (ADR-004)"
        )

    def test_version_lookup_is_available_for_history(self) -> None:
        """AC #7: an old version stays readable after supersession.

        Named `find_version` because `Constitution.version` would shadow `AggregateRoot.version`
        (the optimistic-concurrency counter, ADR-002) — a collision mypy reported during the freeze.
        """
        assert callable(Constitution.find_version)
        assert list(inspect.signature(Constitution.find_version).parameters) == ["self", "number"]

    def test_no_method_shadows_the_concurrency_version_field(self) -> None:
        assert not inspect.isfunction(getattr(Constitution, "version", None))
        assert "version" in {f.name for f in dataclasses.fields(Constitution)}

    def test_versions_view_is_read_only(self) -> None:
        """Returning a list would let a caller mutate history in place."""
        assert inspect.signature(Constitution.versions).return_annotation in (
            tuple[ConstitutionVersion, ...],
            "tuple[ConstitutionVersion, ...]",
        )


class TestConstitutionPolicyProjection:
    def test_policy_is_a_frozen_value_object(self) -> None:
        """Detached from history so a determination can quote the rules it used (A-6)."""
        assert issubclass(ConstitutionPolicy, ValueObject)
        assert ConstitutionPolicy.__dataclass_params__.frozen is True  # type: ignore[attr-defined]

    def test_policy_carries_the_version_number(self) -> None:
        assert [f.name for f in dataclasses.fields(ConstitutionPolicy)] == [
            "version_number",
            "cap",
            "threshold",
            "require_signature_for_new_payee",
        ]
