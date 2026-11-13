"""Money — USDC in integer micro-units. No floats, ever.

Canonical: .pi/architecture/modules/authority.md#components
Reference: .pi/architecture/decisions/ADR-002-data-storage-strategy.md

Why this exists at all (it is small and load-bearing):

* USDC has 6 decimals. `0.1 + 0.2 != 0.3` in binary floating point, and this domain compares
  amounts against a cap and against a signed intent. A float that rounds would let a payment
  pass a cap check it should fail.
* Storage is `INTEGER` micro-units (ADR-002), so the domain type is an integer too — the
  boundary is where conversions would sneak in.
* Arithmetic is explicit and auditable: `Money` supports add/subtract/compare and refuses to
  go negative where that would be a bug (a negative reservation is a hole in the cap).

This is a value object: no identity, immutable, equal by amount.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

MICRO_PER_USDC = 1_000_000


class MoneyError(ValueError):
    """An amount that cannot exist in this domain (negative cap, float input, bad precision)."""


@dataclass(frozen=True, slots=True, order=True)
class Money:
    """An immutable USDC amount stored as integer micro-units.

    >>> Money.usdc("42.50").micro_usdc
    42500000
    >>> Money.usdc("42.50") + Money.usdc("7.50") == Money.usdc("50")
    True
    """

    micro_usdc: int

    def __post_init__(self) -> None:
        if isinstance(self.micro_usdc, bool) or not isinstance(self.micro_usdc, int):
            raise MoneyError(
                f"Money takes integer micro-USDC, got {type(self.micro_usdc).__name__}. "
                "Use Money.usdc('1.23') or Money.from_decimal()."
            )
        if self.micro_usdc < 0:
            raise MoneyError(f"Money cannot be negative: {self.micro_usdc}")

    # ── construction ────────────────────────────────────────────────────────
    @classmethod
    def zero(cls) -> Money:
        return cls(0)

    @classmethod
    def usdc(cls, amount: str | int | Decimal) -> Money:
        """Parse a human USDC amount exactly ('42.50', 42, Decimal('0.000001'))."""
        if isinstance(amount, float):
            raise MoneyError("Refusing float input; pass a str or Decimal (ADR-002).")
        try:
            value = Decimal(amount)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise MoneyError(f"Not a valid USDC amount: {amount!r}") from exc
        if value < 0:
            raise MoneyError(f"Money cannot be negative: {amount!r}")
        micro = value * MICRO_PER_USDC
        if micro != micro.to_integral_value():
            raise MoneyError(
                f"USDC has 6 decimals; {amount!r} is more precise than the chain can represent."
            )
        return cls(int(micro))

    @classmethod
    def from_decimal(cls, amount: Decimal) -> Money:
        return cls.usdc(amount)

    # ── arithmetic ──────────────────────────────────────────────────────────
    def __add__(self, other: Money) -> Money:
        return Money(self.micro_usdc + other.micro_usdc)

    def __sub__(self, other: Money) -> Money:
        """Subtraction that cannot silently go negative — a negative balance is a bug."""
        if other.micro_usdc > self.micro_usdc:
            raise MoneyError(f"Subtraction would go negative: {self!r} - {other!r}")
        return Money(self.micro_usdc - other.micro_usdc)

    def __mul__(self, factor: int) -> Money:
        if isinstance(factor, bool) or not isinstance(factor, int):
            raise MoneyError("Money scales by an integer only.")
        return Money(self.micro_usdc * factor)

    # ── predicates ──────────────────────────────────────────────────────────
    @property
    def is_zero(self) -> bool:
        return self.micro_usdc == 0

    def __bool__(self) -> bool:
        return not self.is_zero

    # ── presentation ────────────────────────────────────────────────────────
    @property
    def usdc_decimal(self) -> Decimal:
        return Decimal(self.micro_usdc) / MICRO_PER_USDC

    def __str__(self) -> str:
        return f"{self.usdc_decimal:.6f} USDC"


__all__ = ["MICRO_PER_USDC", "Money", "MoneyError"]
