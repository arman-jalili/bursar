"""CapLedger — the aggregate that makes split-invoice structuring impossible (frozen).

Canonical: .pi/architecture/modules/authority.md#aggregate-cap-ledge
Reference: docs/contracts/authority-contract-freeze.md (A-9 … A-12)

    A-9   committed + reserved + amount <= cap, checked and applied as ONE conditional update
    A-10  a reservation resolves exactly once — committed or released, never both, never twice
    A-11  `committed` never decreases within a day; only `reserved` moves back down
    A-12  the day key is fixed per reservation; a rollover creates a new ledger row

A-9 is the whole point of this aggregate: six 25 USDC invoices against a 150 USDC cap must fail on the
sixth, and that only holds if the check and the reservation are a single atomic step. `try_reserve`
is therefore named `try_` — it refuses instead of over-booking, and the adapter implements the
atomicity as one `UPDATE ... WHERE committed + reserved + :amount <= cap`.

A-11 is the asymmetry that makes the ledger auditable: spend is monotonic within a day, and only a
*released* reservation returns headroom. A ledger that could un-commit settled spend would let the same
cap be spent twice.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime

from src.authority.domain.ids import IntentId, ReservationId
from src.authority.domain.values import Money
from src.shared.domain.aggregate import AggregateRoot

__all__ = ["CapLedger", "Reservation", "ReservationStatus"]


class ReservationStatus(enum.StrEnum):
    """A reservation resolves exactly once (A-10). `HELD` is the only non-terminal state."""

    HELD = "held"
    COMMITTED = "committed"
    RELEASED = "released"


@dataclass(eq=False)
class Reservation:
    """A hold of a specific amount for a specific intent against a specific day (A-10, A-12).

    An entity, not a value object: it has an identity and a lifecycle that Authority and Settlement both
    refer to by id, and "a reservation of 25 USDC" and "this reservation of 25 USDC" are not the same
    thing once one of them is resolved.
    """

    id: ReservationId
    intent_id: IntentId
    amount: Money
    day: str
    expires_at: datetime
    status: ReservationStatus = ReservationStatus.HELD

    @classmethod
    def hold(
        cls, intent_id: IntentId, amount: Money, day: str, expires_at: datetime
    ) -> Reservation:
        """Create a HELD reservation. The ledger, not the caller, decides whether it may exist (A-9)."""
        raise NotImplementedError("A-10 — see module doc")

    def mark_committed(self) -> None:
        """HELD → COMMITTED, once.

        Raises:
            ReservationAlreadyResolved: the reservation was already committed or released (A-10).
        """
        raise NotImplementedError("A-10 — see module doc")

    def mark_released(self) -> None:
        """HELD → RELEASED, once.

        Raises:
            ReservationAlreadyResolved: the reservation was already resolved (A-10).
        """
        raise NotImplementedError("A-10 — see module doc")


@dataclass(eq=False)
class CapLedger(AggregateRoot):
    """Per-day committed and reserved totals across all payees (A-9, A-11)."""

    day: str
    cap: Money
    committed: Money
    reserved: Money

    @property
    def headroom(self) -> Money:
        """`cap - committed - reserved`. Never negative: the invariant forbids the state (A-9)."""
        raise NotImplementedError("A-9 — see module doc")

    def try_reserve(self, intent_id: IntentId, amount: Money, expires_at: datetime) -> Reservation:
        """Reserve atomically, or refuse (A-9).

        Raises:
            CapExceeded: `committed + reserved + amount > cap` — nothing is reserved, so a refusal leaves
                the ledger untouched (A-8, A-9).
        """
        raise NotImplementedError("A-9 — see module doc")

    def commit(self, reservation: Reservation) -> None:
        """Turn a hold into committed spend after a confirmed settlement (A-10, A-11).

        Raises:
            ReservationAlreadyResolved: the reservation is not HELD (A-10).
        """
        raise NotImplementedError("A-10 — see module doc")

    def release(self, reservation: Reservation) -> None:
        """Return a hold to the headroom because the payment provably did not happen (A-10).

        Raises:
            ReservationAlreadyResolved: the reservation is not HELD (A-10).
        """
        raise NotImplementedError("A-10 — see module doc")
