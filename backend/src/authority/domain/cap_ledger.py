"""CapLedger — the aggregate that makes split-invoice structuring impossible (frozen).

Canonical: docs/architecture/modules/authority.md#aggregate-cap-ledge
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

from src.authority.domain.errors import CapExceeded, ReservationAlreadyResolved
from src.authority.domain.events import (
    CapacityCommitted,
    CapacityReleased,
    CapacityReserved,
)
from src.authority.domain.ids import IntentId, ReservationId, new_id
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
        return cls(
            id=ReservationId(new_id()),
            intent_id=intent_id,
            amount=amount,
            day=day,
            expires_at=expires_at,
            status=ReservationStatus.HELD,
        )

    def mark_committed(self) -> None:
        """HELD → COMMITTED, once.

        Raises:
            ReservationAlreadyResolved: the reservation was already committed or released (A-10).
        """
        self._resolve_into(ReservationStatus.COMMITTED)

    def mark_released(self) -> None:
        """HELD → RELEASED, once.

        Raises:
            ReservationAlreadyResolved: the reservation was already resolved (A-10).
        """
        self._resolve_into(ReservationStatus.RELEASED)

    def _resolve_into(self, terminal: ReservationStatus) -> None:
        if self.status is not ReservationStatus.HELD:
            raise ReservationAlreadyResolved(self.id, self.status.value)
        self.status = terminal


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
        return self.cap - self.committed - self.reserved

    def try_reserve(self, intent_id: IntentId, amount: Money, expires_at: datetime) -> Reservation:
        """Reserve atomically, or refuse (A-9).

        Raises:
            CapExceeded: `committed + reserved + amount > cap` — nothing is reserved, so a refusal leaves
                the ledger untouched (A-8, A-9).
        """
        if self.committed + self.reserved + amount > self.cap:
            raise CapExceeded(amount.micro_usdc, self.headroom.micro_usdc)

        reservation = Reservation.hold(intent_id, amount, self.day, expires_at)
        self.reserved = self.reserved + amount
        self.record(
            CapacityReserved(
                aggregate_id=self.day,
                day=self.day,
                reservation_id=reservation.id,
                intent_id=intent_id,
                amount_micro_usdc=amount.micro_usdc,
                committed_micro_usdc=self.committed.micro_usdc,
                reserved_micro_usdc=self.reserved.micro_usdc,
            )
        )
        return reservation

    def commit(self, reservation: Reservation) -> None:
        """Turn a hold into committed spend after a confirmed settlement (A-10, A-11).

        Raises:
            ReservationAlreadyResolved: the reservation is not HELD (A-10).
        """
        self._require_held(reservation)
        self.reserved = self.reserved - reservation.amount
        self.committed = self.committed + reservation.amount
        reservation.mark_committed()
        self.record(
            CapacityCommitted(
                aggregate_id=self.day,
                day=self.day,
                reservation_id=reservation.id,
                intent_id=reservation.intent_id,
                amount_micro_usdc=reservation.amount.micro_usdc,
                committed_micro_usdc=self.committed.micro_usdc,
            )
        )

    def release(self, reservation: Reservation) -> None:
        """Return a hold to the headroom because the payment provably did not happen (A-10).

        Raises:
            ReservationAlreadyResolved: the reservation is not HELD (A-10).
        """
        self._require_held(reservation)
        self.reserved = self.reserved - reservation.amount
        reservation.mark_released()
        self.record(
            CapacityReleased(
                aggregate_id=self.day,
                day=self.day,
                reservation_id=reservation.id,
                intent_id=reservation.intent_id,
                amount_micro_usdc=reservation.amount.micro_usdc,
                reason="settlement_reverted",
            )
        )

    def _require_held(self, reservation: Reservation) -> None:
        if reservation.status is not ReservationStatus.HELD:
            raise ReservationAlreadyResolved(reservation.id, reservation.status.value)
        if reservation.day != self.day:
            # A-12: a hold belongs to the day it was taken on; a rollover is a different row.
            raise ReservationAlreadyResolved(
                reservation.id, reservation.status.value, reservation_day=reservation.day
            )
