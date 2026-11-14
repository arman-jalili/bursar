"""SQLAlchemy adapters for the Authority ports.

Canonical: docs/architecture/modules/authority.md#components
Reference: docs/architecture/decisions/ADR-002-data-storage-strategy.md

Every rule that must survive concurrency is expressed here as **one statement**, not as read-then-write:

* `try_reserve_atomic` is a single conditional `UPDATE ... WHERE committed + reserved + amount <= cap`.
  A `rowcount` of 0 is the refusal — no exception, no over-booking, nothing reserved (A-9).
* `resolve` flips a reservation with `WHERE status = 'held'`; a second call matches no row and raises
  `ReservationAlreadyResolved` **before** touching the ledger totals (A-10). `committed` only ever grows
  and `reserved` only ever shrinks by the amount of that one hold (A-11).
* The day comes from the reservation row, never from the caller, so a late settlement lands in the day
  it reserved against (A-12).

No adapter commits: the unit of work (`session_scope`) owns the transaction (ADR-002).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.authority.domain.approval import Approval
from src.authority.domain.cap_ledger import CapLedger, Reservation
from src.authority.domain.determination import Determination
from src.authority.domain.errors import ReservationAlreadyResolved
from src.authority.domain.ids import ApprovalId, DeterminationId, IntentId, ReservationId
from src.authority.domain.payment_intent import PaymentIntent
from src.authority.domain.repositories import (
    ApprovalRepository,
    CapLedgerRepository,
    DeterminationRepository,
    PaymentIntentRepository,
)
from src.authority.domain.values import Money
from src.authority.infrastructure.mappers import (
    approval_to_domain,
    approval_to_row,
    determination_to_domain,
    determination_to_row,
    events_to_outbox,
    intent_to_domain,
    intent_to_row,
    ledger_to_domain,
    reservation_to_domain,
    reservation_to_row,
)
from src.authority.infrastructure.models import (
    ApprovalRow,
    CapLedgerRow,
    DeterminationRow,
    OutboxRow,
    PaymentIntentRow,
    ReservationRow,
)
from src.shared.domain.errors import ErrorCode, NotFoundError, RefusalError
from src.shared.domain.event import DomainEvent

__all__ = [
    "OutboxWriter",
    "SqlApprovalRepository",
    "SqlCapLedgerRepository",
    "SqlDeterminationRepository",
    "SqlPaymentIntentRepository",
]


class SqlPaymentIntentRepository(PaymentIntentRepository):
    """Persistence for the immutable intent (A-1). `save` has no field-update path."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, intent: PaymentIntent) -> None:
        self._session.add(intent_to_row(intent))

    async def find_by_id(self, id_: IntentId) -> PaymentIntent | None:
        row = await self._session.get(PaymentIntentRow, str(id_))
        return intent_to_domain(row) if row else None

    async def save(self, intent: PaymentIntent) -> None:
        """The only sanctioned "save" is "already exactly this" (A-1).

        There is no update path because an issued intent is the bytes the owner signed. A caller that
        tries to rewrite one gets a conflict, not a silent mutation.
        """
        existing = await self._session.get(PaymentIntentRow, str(intent.id))
        if existing is None:
            self._session.add(intent_to_row(intent))
            return
        if intent_to_domain(existing) != intent:
            raise RefusalError(
                ErrorCode.CONFLICT,
                "An issued payment intent is immutable.",
                details={"intent_id": str(intent.id)},
            )


class SqlDeterminationRepository(DeterminationRepository):
    """Append-only verdict store (A-7)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, determination: Determination) -> None:
        self._session.add(determination_to_row(determination))

    async def find_by_intent(self, intent_id: IntentId) -> Determination | None:
        result = await self._session.execute(
            select(DeterminationRow).where(DeterminationRow.intent_id == str(intent_id))
        )
        row = result.scalar_one_or_none()
        return determination_to_domain(row) if row else None

    async def find_by_id(self, determination_id: DeterminationId) -> Determination | None:
        """Lookup by the verdict's own id (used by `EscalateForSignature`)."""
        row = await self._session.get(DeterminationRow, str(determination_id))
        return determination_to_domain(row) if row else None


class SqlCapLedgerRepository(CapLedgerRepository):
    """The ledger's atomicity boundary (A-9 … A-12).

    `cap` is injected because the day's cap comes from the constitution read that produced the verdict
    (A-6) — the adapter must not go and read a *different* version behind the service's back.
    """

    def __init__(self, session: AsyncSession, cap: Money | None = None) -> None:
        self._session = session
        self._cap = cap

    async def ledger_for(self, day: str) -> CapLedger:
        result = await self._session.execute(
            select(CapLedgerRow)
            .where(CapLedgerRow.day == day)
            .execution_options(populate_existing=True)
        )
        row = result.scalar_one_or_none()
        if row is None:
            if self._cap is None:
                # No row and no cap to seed it with: the caller asked about a day that has never been
                # opened and did not supply the constitution read that would open it (A-6).
                raise NotFoundError("ledger not found", day=day)
            row = CapLedgerRow(
                day=day,
                cap_micro_usdc=self._cap.micro_usdc,
                committed_micro_usdc=0,
                reserved_micro_usdc=0,
            )
            self._session.add(row)
            await self._session.flush()
        return ledger_to_domain(row)

    async def try_reserve_atomic(
        self, day: str, amount: Money, reservation: Reservation
    ) -> bool:
        """One conditional UPDATE (A-9). False means "no headroom", and nothing was reserved."""
        statement = (
            update(CapLedgerRow)
            .where(
                CapLedgerRow.day == day,
                CapLedgerRow.committed_micro_usdc
                + CapLedgerRow.reserved_micro_usdc
                + amount.micro_usdc
                <= CapLedgerRow.cap_micro_usdc,
            )
            .values(
                reserved_micro_usdc=CapLedgerRow.reserved_micro_usdc + amount.micro_usdc
            )
        )
        result = cast(CursorResult[Any], await self._session.execute(statement))
        if result.rowcount != 1:
            return False
        self._session.add(reservation_to_row(reservation))
        await self._session.flush()
        return True

    async def resolve(self, reservation_id: ReservationId, outcome: str) -> None:
        """Commit or release, exactly once (A-10) — the frozen port's shape."""
        await self.resolve_day(reservation_id, outcome)

    async def resolve_day(self, reservation_id: ReservationId, outcome: str) -> str:
        """Same operation, returning the reservation's fixed day (A-12) for the HTTP response."""
        reservation = await self._session.get(ReservationRow, str(reservation_id))
        if reservation is None:
            raise NotFoundError("reservation not found", reservation_id=str(reservation_id))

        target = "committed" if outcome == "committed" else "released"
        resolved = cast(
            CursorResult[Any],
            await self._session.execute(
                update(ReservationRow)
                .where(
                    ReservationRow.id == str(reservation_id), ReservationRow.status == "held"
                )
                .values(status=target, resolved_at=datetime.now(UTC))
            ),
        )
        if resolved.rowcount != 1:
            # Re-read so the refusal names the state it actually found, not the state it guessed.
            await self._session.refresh(reservation)
            raise ReservationAlreadyResolved(str(reservation_id), reservation.status)

        amount = reservation.amount_micro_usdc
        values: dict[str, object] = {
            "reserved_micro_usdc": CapLedgerRow.reserved_micro_usdc - amount
        }
        if target == "committed":
            values["committed_micro_usdc"] = CapLedgerRow.committed_micro_usdc + amount
        await self._session.execute(
            update(CapLedgerRow)
            .where(CapLedgerRow.day == reservation.day)
            .values(**values)
        )
        return reservation.day

    async def find_reservation(self, reservation_id: ReservationId) -> Reservation | None:
        row = await self._session.get(ReservationRow, str(reservation_id))
        return reservation_to_domain(row) if row else None


class SqlApprovalRepository(ApprovalRepository):
    """Persistence for signature requests (A-13 … A-15)."""

    def __init__(self, session: AsyncSession, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or datetime.now(UTC)

    async def add(self, approval: Approval) -> None:
        self._session.add(approval_to_row(approval))

    async def find_by_id(self, id_: ApprovalId) -> Approval | None:
        row = await self._session.get(ApprovalRow, str(id_))
        return approval_to_domain(row) if row else None

    async def find_pending(self) -> list[Approval]:
        """Unconsumed, unexpired approvals — the owner's inbox (A-14).

        Expiry is filtered here in Python as well as in the query: a row written by another process
        with a naive timestamp must not appear as still-signable.
        """
        result = await self._session.execute(
            select(ApprovalRow)
            .where(ApprovalRow.consumed_at.is_(None))
            .order_by(ApprovalRow.expires_at)
        )
        pending: list[Approval] = []
        for row in result.scalars():
            approval = approval_to_domain(row)
            if approval.expires_at >= self._now:
                pending.append(approval)
        return pending

    async def save(self, approval: Approval) -> None:
        row = await self._session.get(ApprovalRow, str(approval.id))
        if row is None:
            self._session.add(approval_to_row(approval))
            return
        payload = approval_to_row(approval)
        row.consumed_at = payload.consumed_at
        row.signature_hex = payload.signature_hex
        row.signer = payload.signer
        row.signed_digest = payload.signed_digest


class OutboxWriter:
    """Appends drained events to `authority_outbox` inside the caller's transaction (ADR-003)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, events: tuple[DomainEvent, ...]) -> None:
        for row in events_to_outbox(events):
            self._session.add(OutboxRow(**row))
