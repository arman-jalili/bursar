"""ValueObject — immutable, equal by value, validated at construction.

Canonical: .pi/architecture/modules/mandate.md#value-objects-with-entity-vs-vo-justification
Reference: .pi/architecture/decisions/ADR-001-architecture-pattern.md

The point of the base class is the *validation contract*: an invalid value object must be
unconstructible, not merely rejected later. `Cap(-5)` must raise, so no downstream check has to
trust that a `Cap` is sane. That is what makes invariants cheap to state and hard to violate.

Usage:

    @dataclass(frozen=True, slots=True)
    class BankDigest(ValueObject):
        hash: str

        def __post_init__(self) -> None:
            if len(self.hash) != 64:
                raise ValueError("digest must be 64 hex chars")

Subclasses are frozen dataclasses; the base supplies nothing mutable to inherit.
"""

from __future__ import annotations

from typing import Any, ClassVar

__all__ = ["ValueObject"]


class ValueObject:
    """Marker + contract for value objects.

    Deliberately empty: the guarantees come from `@dataclass(frozen=True, slots=True)` plus a
    `__post_init__` that validates. A base class with behaviour would tempt subclasses to share
    state, which is precisely what a value object must not do.

    The `_vo_kind` class attribute exists so architecture tests can assert on the modelling
    choice (`entity` vs `value-object`) without parsing docstrings.
    """

    _vo_kind: ClassVar[str] = "value-object"

    def __setattr__(self, name: str, value: Any) -> None:
        raise TypeError(
            f"{type(self).__name__} is a value object and cannot be mutated after construction."
        )
