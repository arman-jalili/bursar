"""ValueObject — invalid values must be unconstructible, not merely rejected later.

Canonical: .pi/architecture/modules/mandate.md#value-objects-with-entity-vs-vo-justification
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from src.shared.domain.value_object import ValueObject


@dataclass(frozen=True, slots=True)
class Cap(ValueObject):
    micro_usdc: int

    def __post_init__(self) -> None:
        if self.micro_usdc <= 0:
            raise ValueError("cap must be positive")


def test_invalid_vo_cannot_exist() -> None:
    with pytest.raises(ValueError, match="positive"):
        Cap(0)
    with pytest.raises(ValueError, match="positive"):
        Cap(-5)


def test_equal_by_value_not_identity() -> None:
    assert Cap(150) == Cap(150)
    assert Cap(150) is not Cap(150)
    assert len({Cap(150), Cap(150), Cap(25)}) == 2


def test_immutable() -> None:
    """`@dataclass(frozen=True)` blocks assignment; ValueObject blocks it for every subclass."""
    cap = Cap(150)
    with pytest.raises(AttributeError, match="cannot assign"):
        cap.micro_usdc = 999  # type: ignore[misc]


def test_hashable_so_it_can_be_a_dict_key() -> None:
    assert {Cap(150): "daily"}[Cap(150)] == "daily"
