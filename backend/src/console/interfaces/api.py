"""The eight console endpoints (frozen surface) — one write, seven reads.

Canonical: docs/architecture/modules/console.md#api-endpoints
Reference: docs/contracts/console-contract-freeze.md §2.11-§2.12

`CONSOLE_ROUTES` is frozen data because it is the contract the React team and the auth matrix are
built against. Exactly one row is `mutating=True`; the read-only suite asserts that and the absence
of creating paths (CON-04). The router is built *from* the table, so a route outside it cannot be
served: an unknown handler name raises `ReadOnlyViolation` instead of being silently skipped.

Handlers are concrete, not an interface: they take `ConsoleDeps` so the router is the only place
that knows the composition. The signature handler reads `request.body()` — raw bytes, no pydantic
body model — because a body model is a rewrite (CON-03).
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from src.console.application.dto import (
    ApprovalInboxItem,
    ConstitutionReadModel,
    EvidenceReadModel,
    PayeeReadModel,
    PaymentReadModel,
    SignatureOutcome,
    VerificationReadModel,
)
from src.console.application.errors import ConsoleRefusal, ReadOnlyViolation
from src.console.application.services import (
    ProjectApprovalInbox,
    ProjectEvidence,
    ProjectPayerBills,
)
from src.console.infrastructure.http import (
    AuthorityHttpAdapter,
    BillingHttpAdapter,
    EvidenceHttpAdapter,
    HttpAdapterConfig,
    MandateHttpAdapter,
    SettlementHttpAdapter,
)
from src.console.interfaces.deps import bearer_token, require_scope
from src.console.interfaces.schemas import (
    ApprovalInboxItemResponse,
    ConstitutionResponse,
    EvidenceResponse,
    PayeeResponse,
    PayerBillResponse,
    SignatureOutcomeResponse,
    VerificationResponse,
)
from src.shared.infrastructure.logging import correlation_id_var

__all__ = [
    "CONSOLE_ROUTES",
    "SIGNATURE_PATH",
    "ConsoleDeps",
    "Route",
    "approval_inbox",
    "build_deps",
    "build_router",
    "constitution",
    "evidence_list",
    "install",
    "payee_list",
    "payer_bill",
    "payer_bills",
    "submit_signature",
    "verify",
]

#: Upstream base URLs. The demo/CI transport answers these paths with recorded payloads; the live
#: composition (`BURSAR_CONSOLE_UPSTREAM=live`) reaches the real services instead.
AUTHORITY_BASE_URL: Final[str] = os.environ.get(
    "BURSAR_CONSOLE_AUTHORITY_URL", "http://127.0.0.1:8001"
)
IN_PROCESS_BASE_URL: Final[str] = "http://127.0.0.1:8000"


@dataclass(frozen=True, slots=True)
class Route:
    """One HTTP row: method, path, required scope, and whether it mutates (CON-04)."""

    method: str
    path: str
    scope: str
    mutating: bool = False
    handler: str = ""


#: The only path in the module that changes state (ADR-005).
SIGNATURE_PATH: Final[str] = "/v1/console/approvals/{id}/signature"

CONSOLE_ROUTES: Final[tuple[Route, ...]] = (
    Route("GET", "/v1/console/approvals", "authority:read", handler="approval_inbox"),
    Route(
        "POST",
        SIGNATURE_PATH,
        "authority:sign",
        mutating=True,
        handler="submit_signature",
    ),
    Route("GET", "/v1/console/bills", "console:read", handler="payer_bills"),
    Route("GET", "/v1/console/bills/{invoice_id}", "console:read", handler="payer_bill"),
    Route("GET", "/v1/console/payees", "console:read", handler="payee_list"),
    Route("GET", "/v1/console/constitution", "console:read", handler="constitution"),
    Route("GET", "/v1/console/evidence", "evidence:read", handler="evidence_list"),
    Route("GET", "/v1/console/evidence/{id}/verify", "console:read", handler="verify"),
)


@dataclass(frozen=True, slots=True)
class ConsoleDeps:
    """The three projections the router wires. No session, no repository, no adapter (CON-04)."""

    approval_inbox: ProjectApprovalInbox
    payer_bills: ProjectPayerBills
    evidence: ProjectEvidence


# ── Application-facing handlers (the frozen functions; the router calls these) ──


async def approval_inbox(deps: ConsoleDeps, owner_scope: str) -> tuple[ApprovalInboxItem, ...]:
    """GET /v1/console/approvals — the owner's pending signature requests (CON-01)."""
    return await deps.approval_inbox.execute(owner_scope)


async def submit_signature(
    deps: ConsoleDeps,
    approval_id: str,
    *,
    raw_body: bytes,
    content_type: str,
    owner_scope: str,
) -> SignatureOutcome:
    """POST /v1/console/approvals/{id}/signature — forward, never rewrite (CON-03)."""
    # The body goes to the port exactly as received; this function adds no field and parses nothing.
    return await deps.approval_inbox.submit(
        approval_id,
        raw_body=raw_body,
        content_type=content_type,
        owner_scope=owner_scope,
    )


async def payer_bills(deps: ConsoleDeps, scope: str) -> tuple[PaymentReadModel, ...]:
    """GET /v1/console/bills — household-language bills (CON-06)."""
    return await deps.payer_bills.execute(scope)


async def payer_bill(deps: ConsoleDeps, scope: str, invoice_id: str) -> PaymentReadModel:
    """GET /v1/console/bills/{invoice_id} — one bill for the payer detail screen (CON-06)."""
    return await deps.payer_bills.one(scope, invoice_id)


async def payee_list(deps: ConsoleDeps, owner_scope: str) -> tuple[PayeeReadModel, ...]:
    """GET /v1/console/payees — display-only payee status (CON-01)."""
    return await deps.approval_inbox.payees(owner_scope)


async def constitution(deps: ConsoleDeps, owner_scope: str) -> ConstitutionReadModel:
    """GET /v1/console/constitution — display-only cap/threshold/version (CON-01)."""
    return await deps.approval_inbox.constitution_version(owner_scope)


async def evidence_list(
    deps: ConsoleDeps, owner_scope: str, intent_id: str | None = None
) -> tuple[EvidenceReadModel, ...]:
    """GET /v1/console/evidence — envelope hashes and reason codes (CON-01)."""
    del owner_scope  # the evidence port is scoped by its own adapter
    return await deps.evidence.envelopes(intent_id)


async def verify(deps: ConsoleDeps, owner_scope: str, envelope_id: str) -> VerificationReadModel:
    """GET /v1/console/evidence/{id}/verify — Evidence's verdict, proxied (CON-08)."""
    del owner_scope
    return await deps.evidence.verify(envelope_id)


# ── Router ───────────────────────────────────────────────────────────────────


def _resolve(request: Request, supplied: ConsoleDeps | None) -> ConsoleDeps:
    if supplied is not None:
        return supplied
    resolved: ConsoleDeps = request.app.state.console_deps
    return resolved


def _scope_of(request: Request) -> str:
    return bearer_token(request.headers.get("authorization"))


def build_router(deps: ConsoleDeps | None = None) -> object:
    """Build the FastAPI router from `CONSOLE_ROUTES`.

    `deps` is supplied by tests and by `build_router()` in the composition root; when it is None the
    router reads `app.state.console_deps`, which `install` sets on startup.

    Raises:
        ReadOnlyViolation: a route outside `CONSOLE_ROUTES` was asked for (CON-04).
    """
    router = APIRouter(tags=["console"])

    async def _approvals_endpoint(request: Request) -> list[ApprovalInboxItemResponse]:
        items = await approval_inbox(_resolve(request, deps), _scope_of(request))
        return [ApprovalInboxItemResponse.from_dto(item) for item in items]

    async def _signature_endpoint(request: Request, id: str) -> SignatureOutcomeResponse:
        # `request.body()` is the bytes as received. There is deliberately no pydantic body model.
        raw_body = await request.body()
        outcome = await submit_signature(
            _resolve(request, deps),
            id,
            raw_body=raw_body,
            content_type=request.headers.get("content-type", "application/json"),
            owner_scope=_scope_of(request),
        )
        return SignatureOutcomeResponse.from_dto(outcome)

    async def _bills_endpoint(request: Request) -> list[PayerBillResponse]:
        bills = await payer_bills(_resolve(request, deps), _scope_of(request))
        return [PayerBillResponse.from_dto(bill) for bill in bills]

    async def _bill_endpoint(request: Request, invoice_id: str) -> PayerBillResponse:
        bill = await payer_bill(_resolve(request, deps), _scope_of(request), invoice_id)
        return PayerBillResponse.from_dto(bill)

    async def _payees_endpoint(request: Request) -> list[PayeeResponse]:
        payees = await payee_list(_resolve(request, deps), _scope_of(request))
        return [PayeeResponse.from_dto(payee) for payee in payees]

    async def _constitution_endpoint(request: Request) -> ConstitutionResponse:
        current = await constitution(_resolve(request, deps), _scope_of(request))
        return ConstitutionResponse.from_dto(current)

    async def _evidence_endpoint(
        request: Request, intent_id: str | None = None
    ) -> list[EvidenceResponse]:
        envelopes = await evidence_list(
            _resolve(request, deps), _scope_of(request), intent_id=intent_id
        )
        return [EvidenceResponse.from_dto(envelope) for envelope in envelopes]

    async def _verify_endpoint(request: Request, id: str) -> VerificationResponse:
        result = await verify(_resolve(request, deps), _scope_of(request), id)
        return VerificationResponse.from_dto(result)

    endpoints: dict[str, tuple[Callable[..., Awaitable[object]], type | None, str]] = {
        "approval_inbox": (
            _approvals_endpoint,
            list[ApprovalInboxItemResponse],
            "Owner approval inbox — exact intent fields",
        ),
        "submit_signature": (
            _signature_endpoint,
            SignatureOutcomeResponse,
            "Submit the owner signature unmodified (the module's only write)",
        ),
        "payer_bills": (
            _bills_endpoint,
            list[PayerBillResponse],
            "Payer bills — household language",
        ),
        "payer_bill": (_bill_endpoint, PayerBillResponse, "One payer bill"),
        "payee_list": (_payees_endpoint, list[PayeeResponse], "Payees and their status"),
        "constitution": (_constitution_endpoint, ConstitutionResponse, "Current constitution"),
        "evidence_list": (_evidence_endpoint, list[EvidenceResponse], "Evidence envelopes"),
        "verify": (_verify_endpoint, VerificationResponse, "Verified / tampered toggle"),
    }

    for route in CONSOLE_ROUTES:
        entry = endpoints.get(route.handler)
        if entry is None:  # pragma: no cover - the table is a literal above
            raise ReadOnlyViolation(
                f"route {route.method} {route.path} has no handler; the console serves only "
                "CONSOLE_ROUTES (CON-04)"
            )
        endpoint, response_model, summary = entry
        router.add_api_route(
            route.path,
            endpoint,
            methods=[route.method],
            response_model=response_model,
            dependencies=[Depends(require_scope(route.scope))],
            name=route.handler,
            summary=summary,
        )
        # The frozen table names the singular `method`; FastAPI stores the plural `methods` set.
        # Expose both so the auth matrix can read the router as it reads `CONSOLE_ROUTES` (CON-04).
        router.routes[-1].method = route.method  # type: ignore[attr-defined]

    return router


def build_deps() -> ConsoleDeps:
    """Compose the three projections over the six upstream adapters (composition root only)."""
    live = os.environ.get("BURSAR_CONSOLE_UPSTREAM") == "live"
    authority = AuthorityHttpAdapter(
        HttpAdapterConfig(base_url=AUTHORITY_BASE_URL, live=live)
    )
    billing = BillingHttpAdapter(HttpAdapterConfig(base_url=IN_PROCESS_BASE_URL, live=live))
    settlement = SettlementHttpAdapter(HttpAdapterConfig(base_url=IN_PROCESS_BASE_URL, live=live))
    mandate = MandateHttpAdapter(HttpAdapterConfig(base_url=IN_PROCESS_BASE_URL, live=live))
    evidence = EvidenceHttpAdapter(HttpAdapterConfig(base_url=IN_PROCESS_BASE_URL, live=live))

    return ConsoleDeps(
        approval_inbox=ProjectApprovalInbox(authority, authority, mandate),
        payer_bills=ProjectPayerBills(billing, settlement),
        evidence=ProjectEvidence(evidence),
    )


def install(app: object) -> None:
    """Compose the console into a FastAPI app (called by the deployable's composition root)."""
    app.include_router(build_router())  # type: ignore[attr-defined]

    # ADR-004: a console refusal is a documented 409 outcome, not a 500. The detail names the
    # violated invariant (e.g. "a settled payer bill must carry payout_simulated: true").
    @app.exception_handler(ConsoleRefusal)  # type: ignore[attr-defined]
    async def _console_refusal(_request: Request, exc: ConsoleRefusal) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "CONFLICT",
                    "message": str(exc),
                    "retryable": False,
                    "correlation_id": correlation_id_var.get(),
                }
            },
        )

    def _start(application: object) -> None:
        application.state.console_deps = build_deps()  # type: ignore[attr-defined]

    app.state.startup_hooks.append(_start)  # type: ignore[attr-defined]
