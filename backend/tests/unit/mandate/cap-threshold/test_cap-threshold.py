"""Contract tests — `Cap` / `Threshold` (mandate v1).

Canonical: docs/architecture/modules/mandate.md#value-objects-with-entity-vs-vo-justification
Reference: docs/architecture/modules/mandate.md#acceptance-criteria (AC #2)

Frozen here: the types, their integer micro-unit field, immutability, and the fact that the
`threshold > cap` rule is *reachable* from `Constitution.append` (it takes both, plus an owner proof).
The validation itself (`Cap(0)` raises, `Threshold > Cap` raises at append) is the
`cap-threshold` item's job — asserting it now would make a contract test go red the moment the rule
was implemented.

Rewritten from the generated placeholder (hyphenated method names → `SyntaxError`).
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest
from src.mandate.domain.constitution import Constitution
from src.mandate.domain.errors import MandateError, ThresholdExceedsCap
from src.mandate.domain.values import Cap, Threshold
from src.shared.domain.errors import ErrorCode
from src.shared.domain.value_object import ValueObject


class TestCapValueObject:
    def test_is_a_frozen_value_object(self) -> None:
        assert issubclass(Cap, ValueObject)
        assert Cap.__dataclass_params__.frozen is True  # type: ignore[attr-defined]

    def test_holds_micro_usdc(self) -> None:
        """Integer micro-units, never a float — a float would let a payment pass a cap check (ADR-002)."""
        assert [f.name for f in dataclasses.fields(Cap)] == ["micro_usdc"]
        assert Cap(micro_usdc=150_000_000).micro_usdc == 150_000_000

    def test_is_immutable_and_hashable(self) -> None:
        cap = Cap(micro_usdc=150_000_000)
        with pytest.raises(AttributeError):
            cap.micro_usdc = 1  # type: ignore[misc]
        assert {Cap(micro_usdc=1): "a"}[Cap(micro_usdc=1)] == "a"

    def test_exposes_at_least(self) -> None:
        signature = inspect.signature(Cap.at_least)
        assert list(signature.parameters) == ["self", "amount_micro"]
        assert signature.return_annotation in (bool, "bool")


class TestThresholdValueObject:
    def test_is_a_frozen_value_object(self) -> None:
        assert issubclass(Threshold, ValueObject)
        assert Threshold.__dataclass_params__.frozen is True  # type: ignore[attr-defined]

    def test_holds_micro_usdc(self) -> None:
        assert [f.name for f in dataclasses.fields(Threshold)] == ["micro_usdc"]

    def test_exposes_exceeded_by(self) -> None:
        signature = inspect.signature(Threshold.exceeded_by)
        assert list(signature.parameters) == ["self", "amount_micro"]
        assert signature.return_annotation in (bool, "bool")

    def test_cap_and_threshold_are_distinct_types(self) -> None:
        """A cap passed where a threshold is expected is a real bug; the types must not be aliases."""
        assert Cap is not Threshold
        assert not issubclass(Cap, Threshold)


class TestThresholdExceedsCapError:
    def test_is_a_mandate_refusal_with_its_own_codes(self) -> None:
        error = ThresholdExceedsCap(threshold_usdc="300", cap_usdc="150")
        assert isinstance(error, MandateError)
        assert error.code is ErrorCode.CONFLICT
        assert error.http_status == 409
        assert error.details["cap_usdc"] == "150"
        assert error.details["threshold_usdc"] == "300"

    def test_message_names_both_numbers(self) -> None:
        """The console shows this to the owner; it must say what conflicted."""
        message = ThresholdExceedsCap(threshold_usdc="300", cap_usdc="150").wire_message
        assert "300" in message and "150" in message


class TestConstitutionAppendSurface:
    def test_append_takes_cap_threshold_actor_and_proof(self) -> None:
        """H-6 is only enforceable because both values arrive together with the owner's proof."""
        signature = inspect.signature(Constitution.append)
        assert list(signature.parameters) == [
            "self",
            "cap",
            "threshold",
            "require_signature_for_new_payee",
            "actor",
            "proof",
        ]

    def test_append_annotations_are_the_value_objects(self) -> None:
        parameters = inspect.signature(Constitution.append).parameters
        assert parameters["cap"].annotation in (Cap, "Cap")
        assert parameters["threshold"].annotation in (Threshold, "Threshold")
