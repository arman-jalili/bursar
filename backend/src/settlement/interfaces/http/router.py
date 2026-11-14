"""The Settlement HTTP router — concrete, registered once in the app shell.

Canonical: .pi/architecture/modules/settlement.md#api-endpoints
Reference: docs/contracts/settlement-contract-freeze.md §2.11

Thin on purpose: translate HTTP into a service call, map the result back. No module rule lives here.

Two write endpoints are declared in the frozen contract but **not implemented** here: `POST
/v1/intents/{intent_id}/dispatch` and `POST /v1/anchors`. They currently answer `501` with a message that
names the reason (the `DispatchPayment`/`SettleOnce` and chain-adapter contract blockers documented in
ADR-009 and the runbook). Returning 501 is deliberate: an endpoint that silently 500s, or one that
"succeeds" against a fake chain, would hide the gap the freeze exists to make visible.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.settlement.application.dto import CostSummaryQuery, ListOrdersQuery
from src.settlement.application.services_impl import (
    CostSummaryService,
    GetOrderService,
    GetReceiptService,
    ListOrdersService,
    ListReceiptsService,
    NullifierStatusService,
)
from src.settlement.interfaces.http.deps import require_any_scope, require_scope
from src.settlement.interfaces.http.schemas import (
    CostSummaryResponse,
    NullifierStatusResponse,
    OrderListResponse,
    OrderResponse,
    ReceiptListResponse,
    ReceiptResponse,
)

__all__ = ["build_router", "build_services", "install"]

_SETTLEMENT_READ = require_scope("settlement:read")
_EVIDENCE_OR_SETTLEMENT_READ = require_any_scope({"evidence:read", "settlement:read"})

_BLOCKED_DISPATCH = (
    "settlement dispatch is not wired: DispatchPayment/SettleOnce are blocked on a frozen-contract "
    "amendment (ChainGateway.submit cannot persist the hash before broadcast, SC-3; SettlementOrder has "
    "no PENDING/ABANDONED transition). See ADR-009 and docs/runbook-settlement.md."
)
_BLOCKED_ANCHOR = (
    "anchoring is not wired: a ChainGateway adapter (web3 + deployed PaymentRouter.sol) does not exist "
    "in this build. See ADR-009 and docs/runbook-settlement.md."
)


def _services(request: Request) -> dict[str, object]:
    return request.app.state.settlement_services


def _order_response(view: object) -> OrderResponse:
    return OrderResponse(
        order_id=view.order_id,  # type: ignore[attr-defined]
        intent_id=view.intent_id,  # type: ignore[attr-defined]
        invoice_id=view.invoice_id,  # type: ignore[attr-defined]
        status=view.status,  # type: ignore[attr-defined]
        amount_micro_usdc=view.amount_micro_usdc,  # type: ignore[attr-defined]
        nullifier=view.nullifier,  # type: ignore[attr-defined]
        tx_hash=view.tx_hash,  # type: ignore[attr-defined]
        chain_id=view.chain_id,  # type: ignore[attr-defined]
    )


def _receipt_response(view: object) -> ReceiptResponse:
    return ReceiptResponse(
        order_id=view.order_id,  # type: ignore[attr-defined]
        tx_hash=view.tx_hash,  # type: ignore[attr-defined]
        block_number=view.block_number,  # type: ignore[attr-defined]
        confirmations=view.confirmations,  # type: ignore[attr-defined]
        status=view.status,  # type: ignore[attr-defined]
        gas_used=view.gas_used,  # type: ignore[attr-defined]
        gas_price=view.gas_price,  # type: ignore[attr-defined]
        fee_micro_usdc=view.fee_micro_usdc,  # type: ignore[attr-defined]
        is_anchor=view.is_anchor,  # type: ignore[attr-defined]
        revert_reason=view.revert_reason,  # type: ignore[attr-defined]
    )


def build_router() -> APIRouter:
    """Build a fresh router (tests build many apps; re-decorating a shared one duplicates routes)."""
    router = APIRouter(tags=["settlement"])

    @router.get("/v1/orders", response_model=OrderListResponse)
    async def list_orders(
        request: Request,
        status_filter: str = Query(default="", alias="status"),
        limit: int = Query(default=50, ge=1, le=200),
        _scopes: frozenset[str] = Depends(_SETTLEMENT_READ),
    ) -> OrderListResponse:
        service: ListOrdersService = _services(request)["list_orders"]  # type: ignore[assignment]
        views = await service.execute(ListOrdersQuery(status=status_filter, limit=limit))
        return OrderListResponse(orders=[_order_response(view) for view in views], count=len(views))

    @router.get("/v1/orders/{order_id}", response_model=OrderResponse)
    async def get_order(
        order_id: str,
        request: Request,
        _scopes: frozenset[str] = Depends(_SETTLEMENT_READ),
    ) -> OrderResponse:
        service: GetOrderService = _services(request)["get_order"]  # type: ignore[assignment]
        return _order_response(await service.execute(order_id))

    @router.get("/v1/orders/{order_id}/receipt", response_model=ReceiptResponse)
    async def get_receipt(
        order_id: str,
        request: Request,
        _scopes: frozenset[str] = Depends(_SETTLEMENT_READ),
    ) -> ReceiptResponse:
        service: GetReceiptService = _services(request)["get_receipt"]  # type: ignore[assignment]
        return _receipt_response(await service.execute(order_id))

    @router.get("/v1/receipts", response_model=ReceiptListResponse)
    async def list_receipts(
        request: Request,
        day: str = Query(default=""),
        _scopes: frozenset[str] = Depends(_SETTLEMENT_READ),
    ) -> ReceiptListResponse:
        day_iso = day or datetime.now(UTC).date().isoformat()
        receipts_service: ListReceiptsService = _services(request)["list_receipts"]  # type: ignore[assignment]
        cost_service: CostSummaryService = _services(request)["cost_summary"]  # type: ignore[assignment]
        views = await receipts_service.execute(day_iso)
        cost = await cost_service.execute(CostSummaryQuery(day_iso=day_iso))
        return ReceiptListResponse(
            receipts=[_receipt_response(view) for view in views],
            cost=CostSummaryResponse(
                day_iso=cost.day_iso,
                receipt_count=cost.receipt_count,
                total_fee_micro_usdc=cost.total_fee_micro_usdc,
                by_network=cost.by_network,
            ),
        )

    @router.get("/v1/nullifiers/{value}", response_model=NullifierStatusResponse)
    async def nullifier_status(
        value: str,
        request: Request,
        _scopes: frozenset[str] = Depends(_EVIDENCE_OR_SETTLEMENT_READ),
    ) -> NullifierStatusResponse:
        service: NullifierStatusService = _services(request)["nullifier_status"]  # type: ignore[assignment]
        spent, order_id = await service.execute(value)
        return NullifierStatusResponse(nullifier=value, spent=spent, order_id=order_id)

    @router.post("/v1/intents/{intent_id}/dispatch", status_code=status.HTTP_501_NOT_IMPLEMENTED)
    async def dispatch(intent_id: str) -> dict[str, str]:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=_BLOCKED_DISPATCH,
        )

    @router.post("/v1/anchors", status_code=status.HTTP_501_NOT_IMPLEMENTED)
    async def anchor() -> dict[str, str]:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=_BLOCKED_ANCHOR,
        )

    return router


def build_services(session_factory: object) -> dict[str, object]:
    """Build one instance of every Settlement read service for the app shell."""
    return {
        "get_order": GetOrderService(session_factory),  # type: ignore[arg-type]
        "list_orders": ListOrdersService(session_factory),  # type: ignore[arg-type]
        "get_receipt": GetReceiptService(session_factory),  # type: ignore[arg-type]
        "list_receipts": ListReceiptsService(session_factory),  # type: ignore[arg-type]
        "cost_summary": CostSummaryService(session_factory),  # type: ignore[arg-type]
        "nullifier_status": NullifierStatusService(session_factory),  # type: ignore[arg-type]
    }


def install(app: object) -> None:
    """Compose the Settlement context into a FastAPI app (called by the deployable's app.py)."""
    app.include_router(build_router())  # type: ignore[attr-defined]

    def _start(application: object) -> None:
        application.state.settlement_services = build_services(  # type: ignore[attr-defined]
            application.state.session_factory  # type: ignore[attr-defined]
        )

    app.state.startup_hooks.append(_start)  # type: ignore[attr-defined]
