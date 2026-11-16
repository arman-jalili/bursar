"""The Authority HTTP router — concrete, registered once in the app shell.

Canonical: docs/architecture/modules/authority.md#api-endpoints
Reference: docs/contracts/authority-contract-freeze.md §2.9

This file is a translator and nothing else: HTTP → command → one application service → response. No
invariant lives here. Every branch is a transport concern:

* **status codes** — a `DENY` determination is a `409` with the domain code, and a `200` body still only
  authorises dispatch when `decision == "allow"` (AC 11);
* **scope checks** — in `deps.py`, before any service is touched;
* **the envelope** — the shared ADR-004 handler turns `BursarError` into the one error shape, so this
  router does not build error bodies by hand;
* **fail closed** — an upstream read failure surfaces as `503 retryable`, never as a `200` with a guess.

The refusal mapping deserves one sentence: a determination is *persisted* before the status code is
chosen, so the `409` can name a `determination_id` the caller (and Evidence) can read back. That is why
the denial is raised here, after the service's transaction commits, rather than inside it.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import select

from src.authority.application.dto import (
    DeterminationView,
    EvaluateAuthorityCommand,
    ReconcileReservationCommand,
    RejectApprovalCommand,
    ReserveCapacityCommand,
    SubmitOwnerSignatureCommand,
)
from src.authority.application.precondition import PreconditionCheck
from src.authority.application.queries import AuthorityQueries
from src.authority.application.services_impl import (
    EscalateForSignatureService,
    EvaluateAuthorityService,
    ReconcileReservationService,
    RejectApprovalService,
    ReserveCapacityService,
    SubmitOwnerSignatureService,
)
from src.authority.domain.errors import AuthorityRefusal, CapExceeded
from src.authority.domain.values import DenialReason
from src.authority.infrastructure.models import ApprovalRow, OutboxRow, ReservationRow
from src.authority.interfaces.http.deps import require_scope
from src.authority.interfaces.http.schemas import (
    ApprovalResponse,
    AuditRecord,
    AuditResponse,
    DeterminationResponse,
    GateApprovalResponse,
    GateCapacityRequest,
    GateCapacityResponse,
    IntentResponse,
    LedgerResponse,
    PreconditionCheckRequest,
    PreconditionCheckResponse,
    RejectResponse,
    SettlementOutcomeRequest,
    SettlementOutcomeResponse,
    SignatureRequest,
    SignatureResponse,
)
from src.shared.domain.errors import ErrorCode
from src.shared.infrastructure.logging import get_logger

__all__ = ["build_router", "build_services", "install"]

#: Determination reason code → the wire code the envelope carries. Both sets are closed; this is the one
#: place they meet, and a missing entry is a bug the refusal path would otherwise hide as CONFLICT.
_REASON_TO_CODE: dict[str, ErrorCode] = {
    DenialReason.PAYEE_FROZEN.value: ErrorCode.PAYEE_FROZEN,
    DenialReason.PAYEE_QUARANTINED.value: ErrorCode.PAYEE_QUARANTINED,
    DenialReason.DIGEST_MISMATCH.value: ErrorCode.DIGEST_MISMATCH,
    DenialReason.DUPLICATE_INVOICE.value: ErrorCode.DUPLICATE_INVOICE,
    DenialReason.CAP_EXCEEDED.value: ErrorCode.CAP_EXCEEDED,
    DenialReason.AMOUNT_MISMATCH.value: ErrorCode.AMOUNT_MISMATCH,
    DenialReason.BUDGET_EXHAUSTED.value: ErrorCode.BUDGET_EXHAUSTED,
    DenialReason.APPROVAL_INVALID.value: ErrorCode.APPROVAL_INVALID,
}


def _refusal_from(
    *, reason_codes: tuple[str, ...], determination_id: str = "", intent_id: str = ""
) -> AuthorityRefusal:
    """Build the documented 409 for a DENY. Never a 500, and never a 200 (AC 11)."""
    primary = reason_codes[0] if reason_codes else ""
    refusal = AuthorityRefusal(
        _REASON_TO_CODE.get(primary, ErrorCode.CONFLICT),
        "The payment was refused; nothing was dispatched.",
        details={
            "reason_codes": ",".join(reason_codes),
            "determination_id": determination_id,
            "intent_id": intent_id,
        },
    )
    refusal.reason_code = primary or refusal.reason_code
    return refusal


def _services(request: Request) -> dict[str, object]:
    """Per-request service instances bound to the app's session factory."""
    return request.app.state.authority_services


def build_router() -> APIRouter:
    """Build a fresh router (re-decorating one shared instance would duplicate OpenAPI operations)."""
    router = APIRouter(prefix="/v1", tags=["authority"])

    # ── Lock 2: the enforcement entry ──────────────────────────────────────
    @router.post(
        "/precondition/check",
        response_model=PreconditionCheckResponse,
        dependencies=[Depends(require_scope("authority:evaluate"))],
        summary="Precondition check (AC 11) — any non-2xx fails closed",
    )
    async def precondition_check(
        body: PreconditionCheckRequest,
        request: Request,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> PreconditionCheckResponse:
        service: PreconditionCheck = _services(request)["precondition"]  # type: ignore[assignment]
        result = await service.execute(
            intent_id=body.intent_id,
            invoice_id=body.invoice_id,
            payee_id=body.payee_id,
            amount_micro_usdc=body.amount_micro_usdc,
        )
        if result.decision == "deny":
            # The determination is already committed, so the refusal can reference it.
            raise _refusal_from(
                reason_codes=result.reason_codes,
                determination_id=result.determination_id,
                intent_id=result.intent.intent_id,
            )
        return PreconditionCheckResponse(
            decision=result.decision,  # type: ignore[arg-type]
            reason_codes=result.reason_codes,
            determination_id=result.determination_id,
        )

    # ── evaluation ─────────────────────────────────────────────────────────
    @router.post(
        "/attempts/{attempt_id}/evaluate",
        response_model=DeterminationResponse,
        dependencies=[Depends(require_scope("authority:evaluate"))],
        summary="Evaluate an attempt against the in-force rules (FR-011)",
    )
    async def evaluate_attempt(attempt_id: str, request: Request) -> DeterminationResponse:
        service: EvaluateAuthorityService = _services(request)["evaluate"]  # type: ignore[assignment]
        result = await service.execute(
            EvaluateAuthorityCommand(attempt_id=attempt_id, household_id="")
        )
        if result.determination.verdict == "deny":
            raise _refusal_from(
                reason_codes=result.determination.reason_codes,
                determination_id=result.determination.determination_id,
                intent_id=result.intent.intent_id,
            )
        return _determination_response(result.determination)

    # ── reads ──────────────────────────────────────────────────────────────
    @router.get(
        "/intents/{intent_id}",
        response_model=IntentResponse,
        dependencies=[Depends(require_scope("authority:read"))],
        summary="The immutable intent (A-1)",
    )
    async def get_intent(intent_id: str, request: Request) -> IntentResponse:
        queries: AuthorityQueries = _services(request)["queries"]  # type: ignore[assignment]
        view = await queries.intent(intent_id)
        return IntentResponse(
            intent_id=view.intent_id,
            invoice_id=view.invoice_id,
            payee_id=view.payee_id,
            payee_address=view.payee_address,
            amount_micro_usdc=view.amount_micro_usdc,
            bank_digest=view.bank_digest,
            is_new_payee=view.is_new_payee,
            requires_owner_signature=view.requires_owner_signature,
            constitution_version=view.constitution_version,
        )

    @router.get(
        "/intents/{intent_id}/determination",
        response_model=DeterminationResponse,
        dependencies=[Depends(require_scope("authority:read"))],
        summary="The verdict, its reason codes and the version consulted (A-5 … A-7)",
    )
    async def get_determination(intent_id: str, request: Request) -> DeterminationResponse:
        queries: AuthorityQueries = _services(request)["queries"]  # type: ignore[assignment]
        determination = await queries.determination(intent_id)
        granted = await queries.approval_granted(intent_id)
        return _determination_response(determination, approval_granted=granted)

    @router.get(
        "/ledger/{day}",
        response_model=LedgerResponse,
        dependencies=[Depends(require_scope("authority:read"))],
        summary="One day's cap state (A-9 … A-12)",
    )
    async def get_ledger(day: str, request: Request) -> LedgerResponse:
        queries: AuthorityQueries = _services(request)["queries"]  # type: ignore[assignment]
        view = await queries.ledger(day)
        return LedgerResponse(
            day=view.day,
            cap_micro_usdc=view.cap_micro_usdc,
            committed_micro_usdc=view.committed_micro_usdc,
            reserved_micro_usdc=view.reserved_micro_usdc,
            headroom_micro_usdc=view.headroom_micro_usdc,
        )

    # ── approvals ──────────────────────────────────────────────────────────
    @router.get(
        "/approvals/inbox",
        dependencies=[Depends(require_scope("authority:read"))],
        summary="Owner inbox with the exact intent fields the console renders (FR-024)",
    )
    async def approval_inbox(request: Request) -> dict[str, object]:
        queries: AuthorityQueries = _services(request)["queries"]  # type: ignore[assignment]
        return {"items": await queries.approval_inbox()}

    @router.get(
        "/approvals",
        response_model=list[ApprovalResponse],
        dependencies=[Depends(require_scope("authority:read"))],
        summary="The owner's signature inbox (A-13, A-14)",
    )
    async def list_approvals(
        request: Request,
        status_filter: Literal["pending"] = Query(default="pending", alias="status"),
    ) -> list[ApprovalResponse]:
        queries: AuthorityQueries = _services(request)["queries"]  # type: ignore[assignment]
        views = await queries.approvals(status_filter)
        return [
            ApprovalResponse(
                approval_id=view.approval_id,
                intent_id=view.intent_id,
                typed_data_hash=view.typed_data_hash,
                expires_at=view.expires_at,
                status=view.status,
            )
            for view in views
        ]

    @router.post(
        "/approvals/{approval_id}/signature",
        response_model=SignatureResponse,
        dependencies=[Depends(require_scope("authority:sign"))],
        summary="Submit the owner's signature for one bound intent (A-13 … A-15)",
    )
    async def submit_signature(
        approval_id: str,
        body: SignatureRequest,
        request: Request,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> SignatureResponse:
        service: SubmitOwnerSignatureService = _services(request)["signature"]  # type: ignore[assignment]
        result = await service.execute(
            SubmitOwnerSignatureCommand(
                approval_id=approval_id, signature_hex=body.signature_hex
            )
        )
        return SignatureResponse(
            granted=result.granted,
            approval_id=result.approval_id,
            events=result.events,
        )

    @router.post(
        "/approvals/{approval_id}/reject",
        response_model=RejectResponse,
        dependencies=[Depends(require_scope("authority:sign"))],
        summary="The owner declines a pending signature request (A-14)",
    )
    async def reject_approval(
        approval_id: str,
        request: Request,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> RejectResponse:
        service: RejectApprovalService = _services(request)["reject"]  # type: ignore[assignment]
        result = await service.execute(RejectApprovalCommand(approval_id=approval_id))
        return RejectResponse(
            rejected=result.rejected,
            approval_id=result.approval_id,
            intent_id=result.intent_id,
            events=result.events,
        )

    # ── the audit read ─────────────────────────────────────────────────────
    @router.get(
        "/audit/approvals",
        response_model=AuditResponse,
        dependencies=[Depends(require_scope("authority:read"))],
        summary="The owner's approval decisions, from the transactional outbox",
    )
    async def audit_approvals(request: Request) -> AuditResponse:
        """Requested / granted / rejected, newest first — including a rejection that sent nothing.

        The console reads this over HTTP rather than from the shared SQLite file, so a decision
        the owner just made is visible immediately.
        """
        factory = request.app.state.session_factory
        async with factory() as session:
            rows = (
                await session.execute(
                    select(
                        OutboxRow.event_name,
                        OutboxRow.correlation_id,
                        OutboxRow.occurred_at,
                    )
                    .where(
                        OutboxRow.event_name.in_(
                            ("ApprovalRequested", "ApprovalGranted", "ApprovalRejected")
                        )
                    )
                    .order_by(OutboxRow.occurred_at.desc())
                    .limit(20)
                )
            ).all()
        return AuditResponse(
            records=[
                AuditRecord(
                    event=row.event_name,
                    intent_id=row.correlation_id,
                    occurred_at=row.occurred_at.isoformat(),
                )
                for row in rows
            ]
        )

    # ── the gate's facts ───────────────────────────────────────────────────
    # These two reads back the operator-authored checks Rigorix runs immediately before dispatch.
    # They are facts, not verdicts: the reservation and the refusal are the gate's decision, and
    # Rigorix writes both into the signed envelope.
    @router.get(
        "/gate/approval/{intent_id}",
        response_model=GateApprovalResponse,
        dependencies=[Depends(require_scope("authority:read"))],
        summary="Does the gate need the owner's signature for this intent, and does it have it?",
    )
    async def gate_approval(intent_id: str, request: Request) -> GateApprovalResponse:
        queries: AuthorityQueries = _services(request)["queries"]  # type: ignore[assignment]
        factory = request.app.state.session_factory
        async with factory() as session:
            required = (
                await session.scalar(
                    select(ApprovalRow.id).where(ApprovalRow.intent_id == intent_id).limit(1)
                )
            ) is not None
        granted = (not required) or await queries.approval_granted(intent_id)
        return GateApprovalResponse(intent_id=intent_id, required=required, granted=granted)

    @router.post(
        "/gate/capacity",
        response_model=GateCapacityResponse,
        dependencies=[Depends(require_scope("authority:sign"))],
        summary="Claim the payment's amount against the daily capacity, atomically",
    )
    async def gate_capacity(
        body: GateCapacityRequest, request: Request
    ) -> GateCapacityResponse:
        services = _services(request)
        queries: AuthorityQueries = services["queries"]  # type: ignore[assignment]
        factory = request.app.state.session_factory
        day = datetime.now(UTC).date().isoformat()
        # A retry of the same intent is the hold it already owns, not a second hold.
        async with factory() as session:
            held = await session.scalar(
                select(ReservationRow.id)
                .where(
                    ReservationRow.intent_id == body.intent_id,
                    ReservationRow.status == "held",
                )
                .limit(1)
            )
        allowed = True
        if held is None:
            service: ReserveCapacityService = services["reserve"]  # type: ignore[assignment]
            try:
                await service.execute(
                    ReserveCapacityCommand(
                        intent_id=body.intent_id,
                        amount_micro_usdc=body.amount_micro_usdc,
                    )
                )
            except CapExceeded:
                allowed = False
        ledger = await queries.ledger(day)
        return GateCapacityResponse(
            intent_id=body.intent_id,
            allowed=allowed,
            cap_micro_usdc=ledger.cap_micro_usdc,
            committed_micro_usdc=ledger.committed_micro_usdc,
            reserved_micro_usdc=ledger.reserved_micro_usdc,
            headroom_micro_usdc=ledger.headroom_micro_usdc,
        )

    # ── settlement callback ────────────────────────────────────────────────
    @router.post(
        "/settlements/{reservation_id}/outcome",
        response_model=SettlementOutcomeResponse,
        dependencies=[Depends(require_scope("settlement:read"))],
        summary="Commit or release a reservation, exactly once (A-10)",
    )
    async def settlement_outcome(
        reservation_id: str,
        body: SettlementOutcomeRequest,
        request: Request,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> SettlementOutcomeResponse:
        services = _services(request)
        queries: AuthorityQueries = services["queries"]  # type: ignore[assignment]
        # 404 before any mutation: an unknown reservation must not be "helpfully" created.
        day, _ = await queries.reservation_of(reservation_id)

        service: ReconcileReservationService = services["reconcile"]  # type: ignore[assignment]
        result = await service.execute(
            ReconcileReservationCommand(reservation_id=reservation_id, outcome=body.outcome)
        )
        ledger = await queries.ledger(day)
        return SettlementOutcomeResponse(
            reservation_id=result.reservation_id,
            day=ledger.day,
            cap_micro_usdc=ledger.cap_micro_usdc,
            committed_micro_usdc=ledger.committed_micro_usdc,
            reserved_micro_usdc=ledger.reserved_micro_usdc,
            headroom_micro_usdc=ledger.headroom_micro_usdc,
            events=result.events,
        )

    return router


def _determination_response(
    view: DeterminationView, *, approval_granted: bool = False
) -> DeterminationResponse:
    return DeterminationResponse(
        determination_id=view.determination_id,
        intent_id=view.intent_id,
        verdict=view.verdict,  # type: ignore[arg-type]
        reason_codes=view.reason_codes,
        constitution_version=view.constitution_version,
        payee_status=view.payee_status,
        read_at=view.read_at,
        approval_granted=approval_granted,
    )


def build_services(session_factory: object) -> dict[str, object]:
    """Build one instance of every catalog service for the app shell.

    The startup hook runs after the engine exists, because a session factory is the seam every service
    takes (ADR-002). Upstream adapters are not injected here: the defaults read Mandate in the same
    transaction and fail closed on Billing until its persistence layer lands. The single-database
    deployment opts into the SQL read-through with `BURSAR_BILLING_READ_MODE=shared`.
    """
    from src.authority.infrastructure.adapters import SqlAttemptViewPort

    shared = os.environ.get("BURSAR_BILLING_READ_MODE", "unavailable") == "shared"
    attempts = SqlAttemptViewPort(session_factory) if shared else None
    # Demo mode: Rigorix is the only decider/executor. This service keeps the intent, the approval
    # request and the facts the gate checks; it neither refuses on capacity nor reserves it.
    gate_mode = os.environ.get("BURSAR_GATE_MODE", "authority").strip().lower() == "rigorix"
    logger = get_logger(__name__)
    if gate_mode:
        logger.info("authority.gate_mode", extra={"gate_mode": "rigorix"})
    else:
        # The demo's refusals must reach Rigorix to be signed. In authority mode a cap refusal
        # happens before dispatch, so no envelope and no trail exist for it.
        logger.warning(
            "authority.gate_mode.disabled",
            extra={"gate_mode": "authority", "effect": "refusals leave no signed envelope"},
        )
    return {
        "precondition": PreconditionCheck(session_factory),  # type: ignore[arg-type]
        "evaluate": EvaluateAuthorityService(  # type: ignore[arg-type]
            session_factory, attempts=attempts, gate_mode=gate_mode
        ),
        "reserve": ReserveCapacityService(session_factory),  # type: ignore[arg-type]
        "escalate": EscalateForSignatureService(session_factory),  # type: ignore[arg-type]
        "signature": SubmitOwnerSignatureService(  # type: ignore[arg-type]
            session_factory, gate_mode=gate_mode
        ),
        "reject": RejectApprovalService(session_factory),  # type: ignore[arg-type]
        "reconcile": ReconcileReservationService(session_factory),  # type: ignore[arg-type]
        "queries": AuthorityQueries(session_factory),  # type: ignore[arg-type]
    }


def install(app: object) -> None:
    """Compose the Authority context into a FastAPI app (called by the deployable's app.py)."""
    app.include_router(build_router())  # type: ignore[attr-defined]

    def _start(application: object) -> None:
        application.state.authority_services = build_services(  # type: ignore[attr-defined]
            application.state.session_factory  # type: ignore[attr-defined]
        )

    app.state.startup_hooks.append(_start)  # type: ignore[attr-defined]
