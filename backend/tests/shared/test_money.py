"""Money — exact USDC arithmetic (ADR-002).

The tests that matter are the ones that would catch a float sneaking into a cap comparison.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from src.shared.domain.money import MICRO_PER_USDC, Money, MoneyError


def test_usdc_parses_exactly() -> None:
    assert Money.usdc("42.50").micro_usdc == 42_500_000
    assert Money.usdc("0.000001").micro_usdc == 1
    assert Money.usdc(7).micro_usdc == 7 * MICRO_PER_USDC


def test_decimal_avoids_binary_float_error() -> None:
    # The reason this type exists: 0.1 + 0.2 != 0.3 in floats.
    total = Money.usdc("0.1") + Money.usdc("0.2")
    assert total == Money.usdc(Decimal("0.3"))
    assert total.micro_usdc == 300_000


def test_rejects_float_input() -> None:
    with pytest.raises(MoneyError, match="float"):
        Money.usdc(0.1)  # type: ignore[arg-type]


def test_rejects_excess_precision() -> None:
    with pytest.raises(MoneyError, match="6 decimals"):
        Money.usdc("0.0000001")


def test_rejects_negative() -> None:
    with pytest.raises(MoneyError, match="negative"):
        Money.usdc("-1")
    with pytest.raises(MoneyError, match="negative"):
        Money(-5)


def test_rejects_bool_as_amount() -> None:
    with pytest.raises(MoneyError):
        Money(True)


def test_subtract_cannot_go_negative() -> None:
    with pytest.raises(MoneyError, match="negative"):
        Money.usdc("10") - Money.usdc("11")


def test_comparison_and_headroom_math() -> None:
    cap = Money.usdc("150")
    committed, reserved = Money.usdc("85"), Money.usdc("40")
    headroom = cap - committed - reserved
    assert headroom == Money.usdc("25")
    assert headroom >= Money.usdc("25")
    assert headroom < Money.usdc("26")


def test_render() -> None:
    assert str(Money.usdc("42.5")) == "42.500000 USDC"
    assert Money.zero().is_zero
    assert not bool(Money.zero())
