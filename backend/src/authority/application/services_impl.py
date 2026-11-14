"""The five catalog application services, implemented (FR-011 … FR-017).

Canonical: .pi/architecture/modules/authority.md#application-services
Reference: docs/contracts/authority-contract-freeze.md §2.7

Every `execute` is **one** `session_scope` = one transaction = one outbox append (ADR-003). The rules
stay in `domain/`: this layer reads the upstream state, calls one intention method, persists, and
returns a DTO. If a rule needs adding, it belongs on an aggregate or in `DeterminationPolicy`.

Three sequencing decisions are contract, not convenience:

* **Intent → determination → reservation**, in that order. A refusal stops after the determination, so a
  DENY can never leave a hold behind (A-8).
* **`PaymentAllowed` is written only after the signature verifies** (A-8). Escalation writes
  `ApprovalRequested`; `SubmitOwnerSignature` writes `ApprovalGranted` + `PaymentAllowed`.
* **A refusal raises and therefore rolls back**, which is exactly "no side effect" — including no
  half-written intent for a cap race. The atomic reservation is the one check that can still refuse after
  the policy said allow (A-9).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.authority.application.dto import (
    DeterminationView,
    EscalateForSignatureCommand,
    EscalateForSignatureResult,
    EvaluateAuthorityCommand,
    EvaluateAuthorityResult,
    IntentView,
    ReconcileReservationCommand,
    ReconcileReservationResult,
    RejectApprovalCommand,
    RejectApprovalResult,
    ReserveCapacityCommand,
    ReserveCapacityResult,
    SubmitOwnerSignatureCommand,
    SubmitOwnerSignatureResult,
)
from src.authority.application.services import (
    EscalateForSignature,
    EvaluateAuthority,
    ReconcileReservation,
    RejectApproval,
    ReserveCapacity,
    SubmitOwnerSignature,
)
from src.authority.domain.approval import Approval, OwnerSignature
from src.authority.domain.cap_ledger import CapLedger, Reservation
from src.authority.domain.determination import Determination
from src.authority.domain.errors import (
    AmountMismatch,
    ApprovalSingleUse,
    AuthorityRefusal,
    CapExceeded,
)
from src.authority.domain.events import (
    ApprovalGranted,
    ApprovalRejected,
    ApprovalRequested,
    AuthorityDetermined,
    CapacityCommitted,
    CapacityReleased,
    CapacityReserved,
    PaymentAllowed,
    PaymentIntentIssued,
    PaymentRefused,
)
from src.authority.domain.ids import ApprovalId, DeterminationId, IntentId, ReservationId
from src.authority.domain.payment_intent import PaymentIntent
from src.authority.domain.policies import StatutoryDeterminationPolicy
from src.authority.domain.ports import AttemptViewPort, InvoiceView
from src.authority.domain.services import ApprovalBinder, DeterminationPolicy
from src.authority.domain.values import DenialReason, DeterminationVerdict, Money
from src.authority.infrastructure.adapters import (
    SqlMandateView,
    SqlOwnerDirectory,
    UnavailableAttemptViewPort,
)
from src.authority.infrastructure.eip712 import EcdsaApprovalBinder
from src.authority.infrastructure.repositories import (
    OutboxWriter,
    SqlApprovalRepository,
    SqlCapLedgerRepository,
    SqlDeterminationRepository,
    SqlPaymentIntentRepository,
)
from src.shared.application.unit_of_work import session_scope
from src.shared.domain.errors import ErrorCode, NotFoundError, RefusalError
from src.shared.domain.event import DomainEvent

__all__ = [
    "APPROVAL_WINDOW",
    "RESERVATION_WINDOW",
    "AuthorityService",
    "EscalateForSignatureService",
    "EvaluateAuthorityService",
    "ReconcileReservationService",
    "ReserveCapacityService",
    "SubmitOwnerSignatureService",
    "determination_view",
    "intent_view",
]

#: How long an owner has to sign one intent (A-14). A standing approval would be an unlimited mandate,
#: which is the thing the constitution exists to prevent.
APPROVAL_WINDOW = timedelta(hours=24)

#: How long a hold waits for a settlement outcome before reconciliation releases it.
RESERVATION_WINDOW = timedelta(hours=24)


def intent_view(intent: PaymentIntent) -> IntentView:
    """Map the aggregate to the transport-neutral view (no domain enum leaves this layer)."""
    return IntentView(
        intent_id=intent.id,
        invoice_id=intent.invoice_id,
        payee_id=intent.payee_id,
        payee_address=intent.payee_address.value,
        amount_micro_usdc=intent.amount.micro_usdc,
        bank_digest=intent.bank_digest.hash,
        is_new_payee=intent.is_new_payee,
        requires_owner_signature=intent.requires_owner_signature,
        constitution_version=intent.constitution_version,
    )


def determination_view(determination: Determination) -> DeterminationView:
    """Map the verdict, keeping the reason codes as strings (evidence and console both key on them)."""
    return DeterminationView(
        determination_id=determination.id,
        intent_id=determination.intent_id,
        verdict=determination.verdict.value,
        reason_codes=tuple(code.value for code in determination.reason_codes),
        constitution_version=determination.constitution_version,
        payee_status=determination.payee_status_read.value,
        read_at=determination.read_at,
    )


class AuthorityService:
    """Shared plumbing: the session factory plus the swap-able policy, binder, ports and clock.

    The ports are constructor parameters (not globals) so a test can substitute an unreachable Mandate
    or a fixed clock and assert the fail-closed behaviour at the same seam production uses.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        attempts: AttemptViewPort | None = None,
        binder: ApprovalBinder | None = None,
        policy: DeterminationPolicy | None = None,
        clock: Callable[[], datetime] | None = None,
        gate_mode: bool = False,
    ) -> None:
        self._factory = session_factory
        self._attempts: AttemptViewPort = attempts or UnavailableAttemptViewPort()
        self._binder: ApprovalBinder = binder or EcdsaApprovalBinder()
        self._policy: DeterminationPolicy = policy or StatutoryDeterminationPolicy()
        self._clock = clock or (lambda: datetime.now(UTC))
        # Demo mode: the capacity and payee-authority decisions belong to Rigorix's gate, not to
        # this service. What remains here is the intent, the approval request, and the facts the
        # gate checks (approval status, the cap ledger it claims against).
        self._gate_mode = gate_mode

    def _mandate(self, session: AsyncSession) -> SqlMandateView:
        return SqlMandateView(session)

    async def _intent_or_404(self, session: AsyncSession, intent_id: str) -> PaymentIntent:
        intent = await SqlPaymentIntentRepository(session).find_by_id(IntentId(intent_id))
        if intent is None:
            raise NotFoundError("intent not found", intent_id=intent_id)
        return intent

    async def _evaluate(
        self,
        session: AsyncSession,
        *,
        invoice: InvoiceView,
        household_id: str,
    ) -> tuple[PaymentIntent, Determination, tuple[str, ...]]:
        """Intent → determination → (reservation | signature request), in one transaction.

        A DENY returns without touching the ledger (A-8). An ALLOW whose atomic reservation loses a
        race raises `CapExceeded`, rolling the transaction back — nothing was reserved.
        """
        now = self._clock()
        mandate = self._mandate(session)
        if not household_id:
            # `POST /v1/attempts/{id}/evaluate` carries only the attempt id: the household is reached
            # through the invoice's payee, read now (A-6) — never guessed from configuration.
            household_id = await mandate.household_of(invoice.payee_id)
        constitution = await mandate.constitution_in_force(household_id)
        payee = await mandate.payee(invoice.payee_id)

        intent = PaymentIntent.from_reads(
            invoice_id=invoice.invoice_id,
            payee=payee,
            constitution_version=constitution.version,
            require_signature_for_new_payee=constitution.require_signature_for_new_payee,
            threshold=constitution.threshold,
            amount=invoice.amount,
        )
        await SqlPaymentIntentRepository(session).add(intent)

        day = now.date().isoformat()
        ledger_repo = SqlCapLedgerRepository(session, constitution.cap)
        ledger = await ledger_repo.ledger_for(day)
        decision = self._policy.decide(
            intent=intent,
            constitution=constitution,
            payee=payee,
            ledger=ledger,
            read_at=now,
        )
        if not self._gate_mode:
            determination = decision
        else:
            # Rigorix owns capacity and the operator's payee authority at the moment of sending,
            # and no reservation happens here: the capacity precondition claims it inside the
            # governed run. Two consequences shape the verdict:
            #
            # * `CAP_EXCEEDED` must NOT refuse here. A payment that does not fit has to reach the
            #   gate so Rigorix can refuse it and sign that refusal; and no signature can create
            #   headroom, so it must not escalate either. It is therefore allowed to be dispatched —
            #   the gate stops it unconditionally.
            # * A signature is only worth asking for when the payment could actually pass: it fits
            #   the headroom now and nothing else (digest, duplicate, frozen payee) already refuses.
            #   Asking the owner to approve an impossible payment is a dead end.
            binding_refusals = tuple(
                code for code in decision.reason_codes if code is not DenialReason.CAP_EXCEEDED
            )
            if binding_refusals:
                determination = Determination.deny(
                    intent_id=intent.id,
                    reasons=binding_refusals,
                    constitution_version=constitution.version,
                    payee_status_read=payee.status,
                    read_at=now,
                    ledger_snapshot=decision.ledger_snapshot,
                )
            elif (
                intent.requires_owner_signature
                and intent.amount.micro_usdc <= ledger.headroom.micro_usdc
            ):
                determination = Determination.escalate(
                    intent_id=intent.id,
                    constitution_version=constitution.version,
                    payee_status_read=payee.status,
                    read_at=now,
                    ledger_snapshot=decision.ledger_snapshot,
                )
            else:
                determination = Determination.allow(
                    intent_id=intent.id,
                    constitution_version=constitution.version,
                    payee_status_read=payee.status,
                    read_at=now,
                    ledger_snapshot=decision.ledger_snapshot,
                )
        await SqlDeterminationRepository(session).append(determination)

        events: list[DomainEvent] = [
            PaymentIntentIssued(
                aggregate_id=intent.id,
                correlation_id=intent.id,
                intent_id=intent.id,
                invoice_id=intent.invoice_id,
                payee_id=intent.payee_id,
                payee_address=intent.payee_address.value,
                amount_micro_usdc=intent.amount.micro_usdc,
                bank_digest=intent.bank_digest.hash,
                is_new_payee=intent.is_new_payee,
                requires_owner_signature=intent.requires_owner_signature,
                constitution_version=intent.constitution_version,
            ),
            AuthorityDetermined(
                aggregate_id=determination.id,
                correlation_id=intent.id,
                determination_id=determination.id,
                intent_id=intent.id,
                verdict=determination.verdict.value,
                reason_codes=tuple(code.value for code in determination.reason_codes),
                constitution_version=determination.constitution_version,
                payee_status=determination.payee_status_read.value,
                read_at_iso=determination.read_at.isoformat(),
            ),
        ]

        if determination.verdict is DeterminationVerdict.DENY:
            events.append(
                PaymentRefused(
                    aggregate_id=intent.id,
                    correlation_id=intent.id,
                    intent_id=intent.id,
                    reason_codes=tuple(code.value for code in determination.reason_codes),
                    refused_at_iso=now.isoformat(),
                )
            )
        elif determination.verdict is DeterminationVerdict.ALLOW and not self._gate_mode:
            reservation = Reservation.hold(intent.id, intent.amount, day, now + RESERVATION_WINDOW)
            if not await ledger_repo.try_reserve_atomic(day, intent.amount, reservation):
                raise CapExceeded(
                    intent.amount.micro_usdc, ledger.headroom.micro_usdc, intent_id=intent.id
                )
            after = await ledger_repo.ledger_for(day)
            events.append(
                PaymentAllowed(
                    aggregate_id=intent.id,
                    correlation_id=intent.id,
                    intent_id=intent.id,
                    amount_micro_usdc=intent.amount.micro_usdc,
                    reservation_id=reservation.id,
                )
            )
            events.append(
                CapacityReserved(
                    aggregate_id=day,
                    correlation_id=intent.id,
                    day=day,
                    reservation_id=reservation.id,
                    intent_id=intent.id,
                    amount_micro_usdc=intent.amount.micro_usdc,
                    committed_micro_usdc=after.committed.micro_usdc,
                    reserved_micro_usdc=after.reserved.micro_usdc,
                )
            )
        elif determination.verdict is DeterminationVerdict.ESCALATE:
            approval = Approval.request(intent, expires_at=now + APPROVAL_WINDOW)
            await SqlApprovalRepository(session, now).add(approval)
            events.append(
                ApprovalRequested(
                    aggregate_id=approval.id,
                    correlation_id=intent.id,
                    approval_id=approval.id,
                    intent_id=intent.id,
                    typed_data_hash=approval.typed_data_hash,
                    expires_at_iso=approval.expires_at.isoformat(),
                    reason="requires_owner_signature",
                )
            )

        await OutboxWriter(session).append(tuple(events))
        return intent, determination, tuple(event.event_name for event in events)


class EvaluateAuthorityService(AuthorityService, EvaluateAuthority):
    """FR-011 — build the intent, re-read Mandate, decide, and reserve (or open a signature request)."""

    async def execute(self, command: EvaluateAuthorityCommand) -> EvaluateAuthorityResult:
        async with session_scope(self._factory) as session:
            attempt, invoice = await self._attempts.load(command.attempt_id)
            # A-3: the attempt may *claim* an amount; the invoice is the source of truth.
            if command.claimed_amount_micro_usdc is not None:
                claimed = Money(command.claimed_amount_micro_usdc)
                if attempt.claimed_amount is not None and attempt.claimed_amount != claimed:
                    raise AmountMismatch(
                        str(claimed.micro_usdc), str(attempt.claimed_amount.micro_usdc)
                    )
                if claimed != invoice.amount:
                    raise AmountMismatch(str(claimed.micro_usdc), str(invoice.amount.micro_usdc))
            intent, determination, events = await self._evaluate(
                session, invoice=invoice, household_id=command.household_id
            )
        return EvaluateAuthorityResult(
            intent=intent_view(intent),
            determination=determination_view(determination),
            events=events,
        )


class ReserveCapacityService(AuthorityService, ReserveCapacity):
    """FR-013 — the atomic hold on its own, for an intent that is already allowed."""

    async def execute(self, command: ReserveCapacityCommand) -> ReserveCapacityResult:
        async with session_scope(self._factory) as session:
            intent = await self._intent_or_404(session, command.intent_id)
            amount = Money(command.amount_micro_usdc)
            if amount != intent.amount:
                raise AmountMismatch(str(amount.micro_usdc), str(intent.amount.micro_usdc))

            now = self._clock()
            day = now.date().isoformat()
            ledger = await SqlCapLedgerRepository(session).ledger_for(day)
            if ledger.cap.is_zero:
                raise RefusalError(
                    ErrorCode.CONFLICT,
                    "No cap is on record for this day.",
                    details={"day": day},
                )
            if ledger.headroom < amount:
                raise CapExceeded(amount.micro_usdc, ledger.headroom.micro_usdc)

            reservation = Reservation.hold(
                intent.id, amount, day, command.expires_at or now + RESERVATION_WINDOW
            )
            repository = SqlCapLedgerRepository(session, ledger.cap)
            if not await repository.try_reserve_atomic(day, amount, reservation):
                raise CapExceeded(amount.micro_usdc, ledger.headroom.micro_usdc)
            after = await repository.ledger_for(day)
            await OutboxWriter(session).append(
                (
                    CapacityReserved(
                        aggregate_id=day,
                        correlation_id=intent.id,
                        day=day,
                        reservation_id=reservation.id,
                        intent_id=intent.id,
                        amount_micro_usdc=amount.micro_usdc,
                        committed_micro_usdc=after.committed.micro_usdc,
                        reserved_micro_usdc=after.reserved.micro_usdc,
                    ),
                )
            )
        return ReserveCapacityResult(
            reservation_id=reservation.id,
            day=day,
            reserved_micro_usdc=after.reserved.micro_usdc,
            headroom_micro_usdc=after.headroom.micro_usdc,
            events=("CapacityReserved",),
        )


class EscalateForSignatureService(AuthorityService, EscalateForSignature):
    """FR-014 — bind a signature request to exactly one intent."""

    async def execute(self, command: EscalateForSignatureCommand) -> EscalateForSignatureResult:
        async with session_scope(self._factory) as session:
            determination = await SqlDeterminationRepository(session).find_by_id(
                DeterminationId(command.determination_id)
            )
            if determination is None:
                raise NotFoundError(
                    "determination not found", determination_id=command.determination_id
                )
            if determination.verdict is not DeterminationVerdict.ESCALATE:
                # Not a refusal of the payment — there is simply nothing to sign.
                raise AuthorityRefusal(
                    ErrorCode.CONFLICT,
                    "This determination is not an escalation.",
                    details={
                        "determination_id": determination.id,
                        "verdict": determination.verdict.value,
                    },
                )
            intent = await self._intent_or_404(session, determination.intent_id)

            now = self._clock()
            approval = Approval.request(
                intent, expires_at=command.expires_at or now + APPROVAL_WINDOW
            )
            await SqlApprovalRepository(session, now).add(approval)
            await OutboxWriter(session).append(
                (
                    ApprovalRequested(
                        aggregate_id=approval.id,
                        correlation_id=intent.id,
                        approval_id=approval.id,
                        intent_id=intent.id,
                        typed_data_hash=approval.typed_data_hash,
                        expires_at_iso=approval.expires_at.isoformat(),
                        reason="requires_owner_signature",
                    ),
                )
            )
        return EscalateForSignatureResult(
            approval_id=approval.id,
            intent_id=intent.id,
            typed_data_hash=approval.typed_data_hash,
            expires_at=approval.expires_at,
            events=("ApprovalRequested",),
        )


class SubmitOwnerSignatureService(AuthorityService, SubmitOwnerSignature):
    """FR-015 — verify against the bound intent and the mandate owner, then authorise dispatch."""

    async def execute(self, command: SubmitOwnerSignatureCommand) -> SubmitOwnerSignatureResult:
        async with session_scope(self._factory) as session:
            now = self._clock()
            approvals = SqlApprovalRepository(session, now)
            approval = await approvals.find_by_id(ApprovalId(command.approval_id))
            if approval is None:
                raise NotFoundError("approval not found", approval_id=command.approval_id)
            if approval.consumed_at is not None:
                # The documented refusal code for a replay is `single_use` (A-14).
                raise ApprovalSingleUse(approval.id)

            intent = await self._intent_or_404(session, approval.intent_id)
            owner = await SqlOwnerDirectory(session).owner_of(intent.payee_id)
            signer = self._binder.recover_signer(
                typed_data_hash=approval.typed_data_hash,
                signature_hex=command.signature_hex,
            )
            signature = OwnerSignature(
                signature_hex=command.signature_hex,
                signer=signer,
                signed_digest=approval.typed_data_hash,
            )
            approval.verify(signature, owner=owner, now=now)
            approval.consume(now=now)
            await approvals.save(approval)

            granted = ApprovalGranted(
                aggregate_id=approval.id,
                correlation_id=intent.id,
                approval_id=approval.id,
                intent_id=intent.id,
                signer=signer.value,
            )
            if self._gate_mode:
                # The signature is the fact the gate needs; the capacity claim happens inside the
                # governed run, not here.
                await OutboxWriter(session).append((granted,))
                events: tuple[str, ...] = ("ApprovalGranted",)
            else:
                # A-8: only now may capacity be reserved and `PaymentAllowed` be published.
                day = now.date().isoformat()
                constitution = await self._mandate(session).constitution_for_payee(intent.payee_id)
                ledger_repo = SqlCapLedgerRepository(session, constitution.cap)
                ledger = await ledger_repo.ledger_for(day)
                reservation = Reservation.hold(
                    intent.id, intent.amount, day, now + RESERVATION_WINDOW
                )
                if not await ledger_repo.try_reserve_atomic(day, intent.amount, reservation):
                    raise CapExceeded(
                        intent.amount.micro_usdc, ledger.headroom.micro_usdc, intent_id=intent.id
                    )
                after = await ledger_repo.ledger_for(day)
                await OutboxWriter(session).append(
                    (
                        granted,
                        PaymentAllowed(
                            aggregate_id=intent.id,
                            correlation_id=intent.id,
                            intent_id=intent.id,
                            amount_micro_usdc=intent.amount.micro_usdc,
                            reservation_id=reservation.id,
                        ),
                        CapacityReserved(
                            aggregate_id=day,
                            correlation_id=intent.id,
                            day=day,
                            reservation_id=reservation.id,
                            intent_id=intent.id,
                            amount_micro_usdc=intent.amount.micro_usdc,
                            committed_micro_usdc=after.committed.micro_usdc,
                            reserved_micro_usdc=after.reserved.micro_usdc,
                        ),
                    )
                )
                events = ("ApprovalGranted", "PaymentAllowed", "CapacityReserved")
        return SubmitOwnerSignatureResult(
            approval_id=approval.id,
            granted=True,
            events=events,
        )


class RejectApprovalService(AuthorityService, RejectApproval):
    """The owner declines: close the request, audit the refusal, dispatch nothing (A-14).

    Rejection is the mirror of signing and gets the same treatment: one transaction, one outbox
    append. The row is consumed without a signature, so the gate's approval check can never read it
    as granted, and a later release attempt is refused by Rigorix as a failed precondition rather
    than silently paying.
    """

    async def execute(self, command: RejectApprovalCommand) -> RejectApprovalResult:
        async with session_scope(self._factory) as session:
            now = self._clock()
            approvals = SqlApprovalRepository(session, now)
            approval = await approvals.find_by_id(ApprovalId(command.approval_id))
            if approval is None:
                raise NotFoundError("approval not found", approval_id=command.approval_id)
            approval.reject(now=now)
            await approvals.save(approval)
            await OutboxWriter(session).append(
                (
                    ApprovalRejected(
                        aggregate_id=approval.id,
                        correlation_id=approval.intent_id,
                        approval_id=approval.id,
                        intent_id=approval.intent_id,
                        reason="owner_rejected",
                    ),
                )
            )
        return RejectApprovalResult(
            approval_id=approval.id,
            intent_id=approval.intent_id,
            events=("ApprovalRejected",),
        )


class ReconcileReservationService(AuthorityService, ReconcileReservation):
    """FR-017 — commit or release exactly once, against the reservation's fixed day (A-10, A-12)."""

    async def execute(self, command: ReconcileReservationCommand) -> ReconcileReservationResult:
        if command.outcome not in ("confirmed", "reverted"):
            raise RefusalError(
                ErrorCode.VALIDATION_FAILED,
                "outcome must be 'confirmed' or 'reverted'.",
                details={"outcome": command.outcome},
            )
        async with session_scope(self._factory) as session:
            repository = SqlCapLedgerRepository(session)
            day = await repository.resolve_day(
                ReservationId(command.reservation_id),
                "committed" if command.outcome == "confirmed" else "released",
            )
            reservation = await repository.find_reservation(
                ReservationId(command.reservation_id)
            )
            if reservation is None:  # pragma: no cover - resolve just read the same row
                raise NotFoundError("reservation not found", reservation_id=command.reservation_id)
            ledger: CapLedger = await repository.ledger_for(day)

            if command.outcome == "confirmed":
                event: DomainEvent = CapacityCommitted(
                    aggregate_id=day,
                    correlation_id=reservation.intent_id,
                    day=day,
                    reservation_id=reservation.id,
                    intent_id=reservation.intent_id,
                    amount_micro_usdc=reservation.amount.micro_usdc,
                    committed_micro_usdc=ledger.committed.micro_usdc,
                )
            else:
                event = CapacityReleased(
                    aggregate_id=day,
                    correlation_id=reservation.intent_id,
                    day=day,
                    reservation_id=reservation.id,
                    intent_id=reservation.intent_id,
                    amount_micro_usdc=reservation.amount.micro_usdc,
                    reason="settlement_reverted",
                )
            await OutboxWriter(session).append((event,))
        return ReconcileReservationResult(
            reservation_id=command.reservation_id,
            ledger_committed_micro_usdc=ledger.committed.micro_usdc,
            ledger_reserved_micro_usdc=ledger.reserved.micro_usdc,
            events=(event.event_name,),
        )
