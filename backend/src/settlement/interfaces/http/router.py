"""The Settlement HTTP router — concrete, registered once in the app shell.

Canonical: .pi/architecture/modules/settlement.md#api-endpoints
Reference: docs/contracts/settlement-contract-freeze.md §2.11

Thin on purpose: translate HTTP into a service call, map the result back. No module rule lives here.

`POST /v1/intents/{intent_id}/dispatch` is **live**: it calls the frozen `DispatchPayment` use case, which
reads Authority's determination (SC-1), signs the payment locally with the chain gateway (so the tx hash
exists before anything is sent — SC-3), persists the hash and the signed bytes, and then runs the one
fixed Rigorix `run_command` that broadcasts them (SC-2). The adapters are installed by this context's
startup hook (`build_services`), and a test replaces the service in `app.state.settlement_services` — no
test reaches the network.

`POST /v1/anchors` still answers `501` with the reason named. The frozen contract defines it and
`AnchorHashService` implements it, but no `PaymentRouter.sol` is deployed on any network this process can
reach (gap G-2, ADR-009). Returning 501 is deliberate: an endpoint that silently 500s, or one that
"succeeds" against a fake chain, would hide the gap the freeze exists to make visible.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from src.settlement.application.dispatch import DispatchPaymentService
from src.settlement.application.dto import (
    CostSummaryQuery,
    DispatchPaymentCommand,
    ListOrdersQuery,
)
from src.settlement.application.queries import InvoiceReceiptQuery
from src.settlement.application.services import DispatchPayment
from src.settlement.application.services_impl import (
    CostSummaryService,
    GetOrderService,
    GetReceiptService,
    ListOrdersService,
    ListReceiptsService,
    NullifierStatusService,
)
from src.settlement.domain.ports import ChainGateway
from src.settlement.domain.values import ChainNetwork
from src.settlement.infrastructure.authority.determination_gate import AuthorityHttpAdapter
from src.settlement.infrastructure.rigorix.command_adapter import RigorixCommandAdapter
from src.settlement.interfaces.http.deps import require_any_scope, require_scope
from src.settlement.interfaces.http.schemas import (
    CostSummaryResponse,
    NullifierStatusResponse,
    OrderListResponse,
    OrderResponse,
    ReceiptListResponse,
    ReceiptResponse,
)
from src.shared.infrastructure.config import Settings

logger = logging.getLogger(__name__)

__all__ = ["DispatchResponse", "build_router", "build_services", "install"]

_SETTLEMENT_READ = require_scope("settlement:read")
_EVIDENCE_OR_SETTLEMENT_READ = require_any_scope({"evidence:read", "settlement:read"})

_BLOCKED_DISPATCH = (
    "settlement dispatch is not composed in this process: the DispatchPayment service was not built "
    "at startup (it needs the Authority gate and the Rigorix executor). See ADR-009 and "
    "docs/runbook-settlement.md."
)
_BLOCKED_ANCHOR = (
    "anchoring is not wired: the ChainGateway adapter exists, but no PaymentRouter.sol is deployed on "
    "the configured chain, so an anchor could only be faked. See ADR-009 and docs/runbook-settlement.md."
)


class DispatchResponse(BaseModel):
    """What a dispatch produced: the order, and the hash that was persisted before broadcast (SC-3).

    Declared here rather than in `schemas.py` because the write surface is this router's: the freeze
    fixes the endpoint shape (§2.11), and the response is a projection of the frozen
    `DispatchPaymentResult`, not a second contract. `tx_hash` is the hash this dispatch **signed**; it is
    `null` only when the request was refused before signing. A `signed` order already carries it, so a
    refused governed broadcast leaves a re-broadcastable record rather than a lie (SC-3).
    """

    order_id: str
    intent_id: str
    status: str
    nullifier: str = ""
    tx_hash: str | None = None
    events: tuple[str, ...] = Field(default_factory=tuple)


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

    @router.get("/v1/receipts/invoice/{invoice_id}")
    async def receipt_for_invoice(
        invoice_id: str,
        request: Request,
        _scopes: frozenset[str] = Depends(_SETTLEMENT_READ),
    ) -> dict[str, object]:
        query: InvoiceReceiptQuery = _services(request)["invoice_receipt"]  # type: ignore[assignment]
        receipt = await query.for_invoice(invoice_id)
        if receipt is None:
            raise HTTPException(status_code=404, detail="no receipt for this invoice")
        return receipt

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

    @router.post(
        "/v1/intents/{intent_id}/dispatch",
        response_model=DispatchResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def dispatch(
        intent_id: str,
        request: Request,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        _scopes: frozenset[str] = Depends(_SETTLEMENT_READ),
    ) -> DispatchResponse:
        """Dispatch one allowed intent (FR-019). No body: there is no path, amount or address to send."""
        services = _services(request)
        if "dispatch" not in services:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=_BLOCKED_DISPATCH
            )
        service: DispatchPayment = services["dispatch"]  # type: ignore[assignment]
        result = await service.execute(
            DispatchPaymentCommand(intent_id=intent_id, idempotency_key=idempotency_key or "")
        )
        return DispatchResponse(
            order_id=result.order_id,
            intent_id=result.intent_id,
            status=result.status,
            nullifier=result.nullifier,
            tx_hash=result.tx_hash,
            events=result.events,
        )

    @router.post("/v1/anchors", status_code=status.HTTP_501_NOT_IMPLEMENTED)
    async def anchor() -> dict[str, str]:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=_BLOCKED_ANCHOR,
        )

    return router


def build_services(
    session_factory: object,
    settings: Settings | None = None,
    chain_gateway: ChainGateway | None = None,
) -> dict[str, object]:
    """Build one instance of every Settlement service for the app shell.

    The read services need only the session factory. The write service also needs its two external
    adapters, which is why `settings` is required for it: the Authority gate and the Rigorix executor are
    composed here, in the context's own install hook, so the deployable uses them and a test can put a
    fake in `app.state.settlement_services` instead.

    `chain_gateway` is `None` when this deployment cannot sign (no settlement key, or no reachable
    node). The dispatch service then refuses every dispatch with `no_chain_gateway` rather than running
    a governed command that has nothing to broadcast — an order that can never be paid would occupy the
    intent's only dispatch slot. The on-chain nullifier read is an additional lock; the local store is
    still the last one. Nothing here fakes a chain.
    """
    services: dict[str, object] = {
        "get_order": GetOrderService(session_factory),  # type: ignore[arg-type]
        "list_orders": ListOrdersService(session_factory),  # type: ignore[arg-type]
        "get_receipt": GetReceiptService(session_factory),  # type: ignore[arg-type]
        "list_receipts": ListReceiptsService(session_factory),  # type: ignore[arg-type]
        "cost_summary": CostSummaryService(session_factory),  # type: ignore[arg-type]
        "nullifier_status": NullifierStatusService(session_factory),  # type: ignore[arg-type]
        "invoice_receipt": InvoiceReceiptQuery(session_factory),  # type: ignore[arg-type]
    }
    if settings is not None:
        services["dispatch"] = build_dispatch_service(
            session_factory, settings, chain_gateway=chain_gateway
        )
    return services


def build_dispatch_service(
    session_factory: object,
    settings: Settings,
    *,
    chain_gateway: ChainGateway | None = None,
) -> DispatchPaymentService:
    """Compose `DispatchPayment` with its three ports (SC-1, SC-2).

    The network comes from configuration through `ChainNetwork.for_chain` — an unconfigured chain id is
    refused rather than defaulted (SC-11), so a wrong `BURSAR_CHAIN_ID` fails at startup instead of
    signing on the wrong chain.
    """
    authority = AuthorityHttpAdapter.from_settings(settings)
    return DispatchPaymentService(
        session_factory,  # type: ignore[arg-type]
        # One adapter object serves both reads: the gate (determination) and the intent facts.
        intents=authority,
        determination=authority,
        executor=RigorixCommandAdapter(settings),
        network=ChainNetwork.for_chain(settings.chain_id),
        chain=chain_gateway,
    )


def _build_chain_gateway(settings: Settings) -> object | None:
    """Build the real `Web3ChainGateway`, or `None` when this deployment cannot sign (G-1).

    Absence is reported at `/readyz` rather than papered over: the on-chain copy of SC-5 is a second
    lock, and a second lock that silently is not there is worse than a named gap.
    """
    if not settings.settlement_private_key.get_secret_value():
        return None
    try:
        from web3 import Web3

        from src.settlement.domain.values import ChainNetwork
        from src.settlement.infrastructure.chain.web3_gateway import Web3ChainGateway

        return Web3ChainGateway(
            Web3(Web3.HTTPProvider(settings.rpc_url)),
            ChainNetwork.for_chain(
                settings.chain_id,
                router_address=settings.payment_router_address,
                usdc_address=settings.usdc_address,
                confirmations_required=settings.confirmations_required,
            ),
            settings,
        )
    except Exception:
        logger.warning("settlement chain gateway not built; on-chain nullifier read is unavailable")
        return None


def install(app: object) -> None:
    """Compose the Settlement context into a FastAPI app (called by the deployable's app.py)."""
    app.include_router(build_router())  # type: ignore[attr-defined]

    def _start(application: object) -> None:
        settings = getattr(application.state, "settings", None)  # type: ignore[attr-defined]
        #: A gateway installed by the deployable wins (tests inject a fake there); otherwise build the
        #: real one from configuration. The build is skipped — never faked — when no settlement key is
        #: configured, because a gateway that cannot sign is a gateway that lies about being able to.
        chain_gateway = getattr(application.state, "settlement_chain_gateway", None)  # type: ignore[attr-defined]
        if chain_gateway is None and settings is not None:
            chain_gateway = _build_chain_gateway(settings)
            application.state.settlement_chain_gateway = chain_gateway  # type: ignore[attr-defined]
        application.state.settlement_services = build_services(  # type: ignore[attr-defined]
            application.state.session_factory,  # type: ignore[attr-defined]
            settings=settings,
            chain_gateway=chain_gateway,
        )

    app.state.startup_hooks.append(_start)  # type: ignore[attr-defined]
