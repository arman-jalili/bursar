"""Read models for the Authority GET endpoints.

Canonical: docs/architecture/modules/authority.md#api-endpoints
Reference: docs/contracts/authority-contract-freeze.md §2.9

Reads are queries, not use cases: they change nothing, emit nothing, and do not belong in the five
catalog services. Keeping them here (rather than in the router) preserves the rule that the transport
never touches a repository — the router still only translates HTTP into a call and a DTO into a body.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.authority.application.dto import DeterminationView, IntentView
from src.authority.application.services_impl import determination_view, intent_view
from src.authority.domain.ids import IntentId, ReservationId
from src.authority.domain.values import Money
from src.authority.infrastructure.models import ApprovalRow, PaymentIntentRow
from src.authority.infrastructure.repositories import (
    SqlApprovalRepository,
    SqlCapLedgerRepository,
    SqlDeterminationRepository,
    SqlPaymentIntentRepository,
)
from src.mandate.infrastructure.models import PayeeRow
from src.shared.application.unit_of_work import session_scope
from src.shared.domain.errors import NotFoundError

__all__ = ["ApprovalView", "AuthorityQueries", "LedgerView"]


@dataclass(frozen=True, slots=True)
class LedgerView:
    """One day's cap state, in the units the wire uses (ADR-002: integer micro-USDC)."""

    day: str
    cap_micro_usdc: int
    committed_micro_usdc: int
    reserved_micro_usdc: int
    headroom_micro_usdc: int


@dataclass(frozen=True, slots=True)
class ApprovalView:
    """The owner's inbox item — enough to sign, and nothing about the account."""

    approval_id: str
    intent_id: str
    typed_data_hash: str
    expires_at: datetime
    status: str


class AuthorityQueries:
    """The four reads the API exposes (`GET /v1/...`)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def intent(self, intent_id: str) -> IntentView:
        async with session_scope(self._factory) as session:
            intent = await SqlPaymentIntentRepository(session).find_by_id(IntentId(intent_id))
            if intent is None:
                raise NotFoundError("intent not found", intent_id=intent_id)
            return intent_view(intent)

    async def determination(self, intent_id: str) -> DeterminationView:
        async with session_scope(self._factory) as session:
            determination = await SqlDeterminationRepository(session).find_by_intent(
                IntentId(intent_id)
            )
            if determination is None:
                raise NotFoundError("determination not found", intent_id=intent_id)
            return determination_view(determination)

    async def ledger(self, day: str) -> LedgerView:
        async with session_scope(self._factory) as session:
            ledger = await SqlCapLedgerRepository(session).ledger_for(day)
            return LedgerView(
                day=ledger.day,
                cap_micro_usdc=ledger.cap.micro_usdc,
                committed_micro_usdc=ledger.committed.micro_usdc,
                reserved_micro_usdc=ledger.reserved.micro_usdc,
                headroom_micro_usdc=ledger.headroom.micro_usdc,
            )

    async def approvals(self, status: str = "pending") -> list[ApprovalView]:
        """`status=pending` is the only supported filter; the router rejects anything else (422)."""
        now = datetime.now(UTC)
        async with session_scope(self._factory) as session:
            approvals = await SqlApprovalRepository(session, now).find_pending()
            return [
                ApprovalView(
                    approval_id=approval.id,
                    intent_id=approval.intent_id,
                    typed_data_hash=approval.typed_data_hash,
                    expires_at=approval.expires_at,
                    status="pending",
                )
                for approval in approvals
            ]

    async def approval_inbox(self) -> list[dict[str, object]]:
        """The owner's pending signature requests with the exact intent fields (FR-024).

        Authority owns the approval and intent rows; the payee display name is read from Mandate's
        table in the same single-database deployment. Amounts cross the wire as exact decimal
        strings, the shape the console's upstream contract names.
        """
        now = datetime.now(UTC)
        async with session_scope(self._factory) as session:
            result = await session.execute(
                select(ApprovalRow, PaymentIntentRow, PayeeRow)
                .join(PaymentIntentRow, PaymentIntentRow.id == ApprovalRow.intent_id)
                .join(PayeeRow, PayeeRow.id == PaymentIntentRow.payee_id)
                .where(ApprovalRow.consumed_at.is_(None))
                .order_by(ApprovalRow.expires_at)
            )
            items: list[dict[str, object]] = []
            for approval, intent, payee in result.all():
                expires = approval.expires_at
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=UTC)
                if expires < now:
                    continue
                items.append(
                    {
                        "approval_id": approval.id,
                        "intent_id": approval.intent_id,
                        "invoice_id": intent.invoice_id,
                        "payee_name": payee.name,
                        "payee_address": intent.payee_address,
                        "amount_usdc": f"{intent.amount_micro_usdc / 1_000_000:.2f}",
                        "bank_digest": intent.bank_digest,
                        "is_new_payee": intent.is_new_payee,
                        "requires_owner_signature": intent.requires_owner_signature,
                        "reason_codes": [],
                        "expires_at": expires.isoformat(),
                        "typed_data_hash": approval.typed_data_hash,
                    }
                )
            return items

    async def approval_granted(self, intent_id: str) -> bool:
        """Whether a verified, unconsumed, unexpired approval exists for this intent (A-13/A-14).

        The determination records what Authority decided; this bit records what the owner then did.
        The settlement gate treats `escalate` + this bit as a permission, so reading it here — live,
        at dispatch time — is what closes the escalate → sign → dispatch path.
        """
        now = datetime.now(UTC)
        async with session_scope(self._factory) as session:
            result = await session.execute(
                select(ApprovalRow)
                .where(ApprovalRow.intent_id == intent_id)
                .order_by(ApprovalRow.expires_at.desc())
            )
            for row in result.scalars():
                if row.signature_hex is None:
                    continue
                # The approval is consumed exactly once *at signing* (A-14), so a consumed row is
                # the strongest evidence the owner authorised this intent. Only an unconsumed row
                # needs its expiry checked.
                if row.consumed_at is not None:
                    return True
                expires = row.expires_at
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=UTC)
                if expires >= now:
                    return True
            return False

    async def reservation_of(self, reservation_id: str) -> tuple[str, Money]:
        """Expose the hold's day and amount for the settlement-outcome response (404 when unknown)."""
        async with session_scope(self._factory) as session:
            reservation = await SqlCapLedgerRepository(session).find_reservation(
                ReservationId(reservation_id)
            )
            if reservation is None:
                raise NotFoundError("reservation not found", reservation_id=reservation_id)
            return reservation.day, reservation.amount
