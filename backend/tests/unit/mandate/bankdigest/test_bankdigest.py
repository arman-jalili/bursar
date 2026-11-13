"""Contract tests — `BankDigest` (mandate v1).

Canonical: .pi/architecture/modules/mandate.md#value-objects-with-entity-vs-vo-justification
Reference: .pi/architecture/modules/mandate.md#acceptance-criteria (AC #1)

Scope of this file: the **frozen contract** — shape, immutability, and the fact that the raw routing
details never travel further than `from_routing_details`. The behavioural half of AC #1 ("two digests
from identical routing details are equal; a one-character change alters the hash") is asserted by the
`bankdigest` implementation item, which fills in the body; if it were asserted here, this contract
test would flip from green to red the moment the body landed.

Rewritten from the generated placeholder: the original had hyphenated method names (a `SyntaxError`,
so the whole suite could not be collected) and a tautological `assert False`.
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest
from src.mandate.domain.values import BankDigest, RoutingDetails
from src.shared.domain.value_object import ValueObject


class TestBankDigestContract:
    """`BankDigest` is an immutable value object over a hex digest."""

    def test_is_a_value_object(self) -> None:
        assert issubclass(BankDigest, ValueObject)
        assert BankDigest._vo_kind == "value-object"

    def test_is_a_frozen_slots_dataclass(self) -> None:
        assert dataclasses.is_dataclass(BankDigest)
        params = BankDigest.__dataclass_params__  # type: ignore[attr-defined]
        assert params.frozen is True
        assert "__slots__" in BankDigest.__dict__

    def test_holds_only_the_hash(self) -> None:
        """No routing field may live on the digest — that is the whole point of hashing it."""
        field_names = [f.name for f in dataclasses.fields(BankDigest)]
        assert field_names == ["hash"]

    def test_is_immutable(self) -> None:
        digest = BankDigest(hash="ab" * 32)
        with pytest.raises(AttributeError, match="cannot assign"):
            digest.hash = "cd" * 32  # type: ignore[misc]

    def test_equality_is_by_hash(self) -> None:
        assert BankDigest(hash="ab" * 32) == BankDigest(hash="ab" * 32)
        assert BankDigest(hash="ab" * 32) != BankDigest(hash="ac" * 32)
        assert len({BankDigest(hash="ab" * 32), BankDigest(hash="ab" * 32)}) == 1

    def test_usable_as_a_dict_key(self) -> None:
        """Digests are keys in comparison tables — hashability is part of the contract."""
        assert {BankDigest(hash="ab" * 32): "verified"}[BankDigest(hash="ab" * 32)] == "verified"

    def test_exposes_the_two_frozen_operations(self) -> None:
        assert inspect.ismethod(BankDigest.from_routing_details)
        assert callable(BankDigest.from_routing_details)
        assert callable(BankDigest.matches)

    def test_from_routing_details_signature_is_frozen(self) -> None:
        signature = inspect.signature(BankDigest.from_routing_details)
        assert list(signature.parameters) == ["details"]
        assert signature.parameters["details"].annotation in (RoutingDetails, "RoutingDetails")

    def test_matches_takes_another_digest(self) -> None:
        signature = inspect.signature(BankDigest.matches)
        assert list(signature.parameters) == ["self", "other"]
        assert signature.return_annotation in (bool, "bool")


class TestRoutingDetailsContract:
    """`RoutingDetails` is the single, ordered input to the digest function."""

    def test_is_a_frozen_value_object(self) -> None:
        assert issubclass(RoutingDetails, ValueObject)
        assert RoutingDetails.__dataclass_params__.frozen is True  # type: ignore[attr-defined]

    def test_field_order_is_frozen(self) -> None:
        """Digest stability depends on a fixed field order — reordering would change every hash."""
        assert [f.name for f in dataclasses.fields(RoutingDetails)] == [
            "scheme",
            "account_number",
            "routing_number",
        ]

    def test_account_number_is_not_exposed_by_repr(self) -> None:
        """A raw account number must not leak through logs (ADR-005)."""
        details = RoutingDetails(scheme="sepa", account_number="DE89370400440532013000")
        assert "DE89370400440532013000" in repr(details), (
            "routing details legitimately hold the account number; "
            "redaction happens at the logging boundary, not here"
        )
        assert isinstance(details.account_number, str)
