"""The Billing HTTP router — concrete, registered once in the app shell.

Canonical: .pi/architecture/modules/billing.md#api-endpoints
Reference: docs/contracts/billing-contract-freeze.md §2.10

Thin on purpose: translate HTTP into commands, call one application service, map the result back. No
module rule lives here. The one *policy* that does belong here is B-5: a proposal carrying any key
outside the frozen vocabulary is rejected with `422 PROPOSAL_REJECTED` before an attempt is built —
rejected, never ignored.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from src.billing.application.dto import ProposePaymentCommand, RecordInvoiceCommand
from src.billing.application.queries import BillingQueries
from src.billing.application.services_impl import (
    GetAttemptService,
    GetInvoiceService,
    ListInvoicesService,
    ProposePaymentService,
    RecordInvoiceService,
)
from src.billing.domain.errors import ProposalRejected
from src.billing.interfaces.http.deps import require_any_scope, require_scope
from src.billing.interfaces.http.schemas import (
    AttemptResponse,
    InvoiceListResponse,
    InvoiceResponse,
    ProposePaymentRequest,
    RecordInvoiceRequest,
    RecordInvoiceResponse,
)

__all__ = ["build_router", "build_services", "install"]

#: The whole accepted proposal vocabulary (B-5). Anything else is rejected by name.
_ALLOWED_PROPOSAL_KEYS = frozenset({"invoice_id", "proposed_amount_micro_usdc"})


def _services(request: Request) -> dict[str, object]:
    """Per-request service instances bound to the app's session factory."""
    services: dict[str, object] = request.app.state.billing_services
    return services


def _invoice_response(view: object) -> InvoiceResponse:
    return InvoiceResponse(
        invoice_id=view.invoice_id,  # type: ignore[attr-defined]
        payee_id=view.payee_id,  # type: ignore[attr-defined]
        invoice_hash=view.invoice_hash,  # type: ignore[attr-defined]
        amount_micro_usdc=view.amount_micro_usdc,  # type: ignore[attr-defined]
        due_date_iso=view.due_date_iso,  # type: ignore[attr-defined]
        presented_digest=view.presented_digest,  # type: ignore[attr-defined]
        status=view.status,  # type: ignore[attr-defined]
    )


def build_router() -> APIRouter:
    """Build a fresh router (tests build many apps; re-decorating one shared router duplicates routes)."""
    router = APIRouter(prefix="/v1", tags=["billing"])

    @router.post(
        "/invoices",
        response_model=RecordInvoiceResponse,
        status_code=201,
        dependencies=[Depends(require_any_scope(frozenset({"mandate:write", "billing:propose"})))],
        summary="Record an invoice (FR-007); a replay returns the original bill (B-3)",
    )
    async def record_invoice(body: RecordInvoiceRequest, request: Request) -> RecordInvoiceResponse:
        result = await _services(request)["record_invoice"].execute(  # type: ignore[attr-defined]
            RecordInvoiceCommand(
                payee_id=body.payee_id,
                amount_micro_usdc=body.amount_micro_usdc,
                due_date=body.due_date,
                document=body.document,
                presented_digest=body.presented_digest,
            )
        )
        return RecordInvoiceResponse(
            invoice=_invoice_response(result.invoice),
            duplicate=result.duplicate,
            events=list(result.events),
        )

    @router.get(
        "/payer/bills",
        dependencies=[Depends(require_scope("console:read"))],
        summary="Payer bills in household language (FR-025 upstream)",
    )
    async def payer_bills(request: Request) -> dict[str, object]:
        queries: BillingQueries = _services(request)["queries"]  # type: ignore[assignment]
        return {"items": await queries.payer_bills()}

    @router.get(
        "/invoices",
        response_model=InvoiceListResponse,
        dependencies=[Depends(require_scope("console:read"))],
        summary="List invoices (read model)",
    )
    async def list_invoices(
        request: Request,
        status: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> InvoiceListResponse:
        views = await _services(request)["list_invoices"].execute(  # type: ignore[attr-defined]
            status=status, cursor=cursor, limit=limit
        )
        return InvoiceListResponse(items=[_invoice_response(view) for view in views])

    @router.get(
        "/invoices/{invoice_id}",
        response_model=InvoiceResponse,
        dependencies=[Depends(require_scope("console:read"))],
        summary="Read one invoice",
    )
    async def get_invoice(invoice_id: str, request: Request) -> InvoiceResponse:
        view = await _services(request)["get_invoice"].execute(invoice_id)  # type: ignore[attr-defined]
        return _invoice_response(view)

    @router.post(
        "/attempts",
        response_model=AttemptResponse,
        status_code=201,
        dependencies=[Depends(require_scope("billing:propose"))],
        summary="Propose a payment attempt — ids only, everything else is rejected (B-5)",
    )
    async def propose_payment(body: ProposePaymentRequest, request: Request) -> AttemptResponse:
        payload = body.model_dump(exclude_none=True)
        offending = set(payload) - _ALLOWED_PROPOSAL_KEYS
        if offending:
            raise ProposalRejected(tuple(sorted(offending)))

        result = await _services(request)["propose_payment"].execute(  # type: ignore[attr-defined]
            ProposePaymentCommand(
                invoice_id=body.invoice_id,
                proposed_amount_micro_usdc=body.proposed_amount_micro_usdc,
            )
        )
        return AttemptResponse(
            attempt_id=result.attempt.attempt_id,
            invoice_id=result.attempt.invoice_id,
            status=result.attempt.status,
            events=list(result.events),
        )

    @router.get(
        "/attempts/{attempt_id}",
        response_model=AttemptResponse,
        dependencies=[Depends(require_scope("console:read"))],
        summary="Read one attempt",
    )
    async def get_attempt(attempt_id: str, request: Request) -> AttemptResponse:
        view = await _services(request)["get_attempt"].execute(attempt_id)  # type: ignore[attr-defined]
        return AttemptResponse(
            attempt_id=view.attempt_id,
            invoice_id=view.invoice_id,
            status=view.status,
        )

    return router


def build_services(session_factory: object) -> dict[str, object]:
    """Build one instance of every Billing service for the app shell."""
    return {
        "record_invoice": RecordInvoiceService(session_factory),  # type: ignore[arg-type]
        "propose_payment": ProposePaymentService(session_factory),  # type: ignore[arg-type]
        "list_invoices": ListInvoicesService(session_factory),  # type: ignore[arg-type]
        "get_invoice": GetInvoiceService(session_factory),  # type: ignore[arg-type]
        "get_attempt": GetAttemptService(session_factory),  # type: ignore[arg-type]
        "queries": BillingQueries(session_factory),  # type: ignore[arg-type]
    }


def install(app: object) -> None:
    """Compose the Billing context into a FastAPI app (called by the deployable's app.py)."""
    app.include_router(build_router())  # type: ignore[attr-defined]

    def _start(application: object) -> None:
        application.state.billing_services = build_services(  # type: ignore[attr-defined]
            application.state.session_factory  # type: ignore[attr-defined]
        )

    app.state.startup_hooks.append(_start)  # type: ignore[attr-defined]
