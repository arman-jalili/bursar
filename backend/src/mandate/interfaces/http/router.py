"""The Mandate HTTP router — concrete, registered once in the app shell.

Canonical: .pi/architecture/modules/mandate.md#api-endpoints
Reference: .pi/architecture/decisions/ADR-004-api-design.md

This file is intentionally thin: it translates HTTP into commands, calls one application service, and
maps the result back. No rule lives here — every branch below is a transport concern (body parsing,
status codes, scope checks).

The `presented-digest` endpoint is the scam surface: it accepts a digest, never routing details,
because there must be no API that could "helpfully" update a payee's bank account (P-2).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from src.mandate.application.dto import (
    CreateMandateCommand,
    FreezePayeeCommand,
    PublishConstitutionVersionCommand,
    ReapprovePayeeDigestCommand,
    RegisterPayeeCommand,
    ReviewPresentedDigestCommand,
)
from src.mandate.application.services_impl import (
    CreateMandateService,
    EligibilityReaderService,
    FreezePayeeService,
    PublishConstitutionVersionService,
    QuarantinePayeeService,
    ReapprovePayeeDigestService,
    RegisterPayeeService,
)
from src.mandate.interfaces.http.deps import require_owner_proof, require_scope
from src.mandate.interfaces.http.schemas import (
    CreateHouseholdRequest,
    EligibilityResponse,
    HouseholdResponse,
    PayeeResponse,
    PresentedDigestRequest,
    PublishVersionRequest,
    ReapproveRequest,
    RegisterPayeeRequest,
    VersionResponse,
)

__all__ = ["build_router", "build_services", "install"]


def _services(request: Request) -> dict[str, object]:
    """Per-request service instances bound to the app's session factory."""
    return request.app.state.mandate_services


def build_router() -> APIRouter:
    """Build a fresh router.

    A function rather than a module-level constant: re-decorating one shared `APIRouter` on every
    `build_app` call (tests build many) would register duplicate routes and duplicate OpenAPI
    operation ids.
    """
    router = APIRouter(prefix="/v1", tags=["mandate"])

    @router.post(
        "/households",
        response_model=HouseholdResponse,
        status_code=201,
        dependencies=[Depends(require_scope("mandate:write"))],
        summary="Create the household mandate (FR-001)",
    )
    async def create_household(body: CreateHouseholdRequest, request: Request) -> HouseholdResponse:
        result = await _services(request)["create_mandate"].execute(  # type: ignore[attr-defined]
            CreateMandateCommand(
                owner_address=body.owner_address,
                owner_name=body.owner_name,
                payer_name=body.payer_name,
                agent_key_id=body.agent_key_id,
                cap_micro_usdc=body.cap_micro_usdc,
                threshold_micro_usdc=body.threshold_micro_usdc,
                require_signature_for_new_payee=body.require_signature_for_new_payee,
                owner_proof=body.owner_proof,
            )
        )
        return HouseholdResponse(
            household_id=result.household_id,
            constitution_id=result.constitution_id,
            owner_id=result.owner_id,
            payer_id=result.payer_id,
            agent_id=result.agent_id,
            version=result.version,
            events=result.events,
        )

    @router.post(
        "/households/{household_id}/constitution/versions",
        response_model=VersionResponse,
        status_code=201,
        dependencies=[Depends(require_scope("mandate:write"))],
        summary="Publish an immutable constitution version (FR-002)",
    )
    async def publish_version(
        household_id: str, body: PublishVersionRequest, request: Request
    ) -> VersionResponse:
        require_owner_proof(body.owner_proof)
        result = await _services(request)["publish_version"].execute(  # type: ignore[attr-defined]
            PublishConstitutionVersionCommand(
                household_id=household_id,
                cap_micro_usdc=body.cap_micro_usdc,
                threshold_micro_usdc=body.threshold_micro_usdc,
                require_signature_for_new_payee=body.require_signature_for_new_payee,
                owner_proof=body.owner_proof,
            )
        )
        version = result.version
        return VersionResponse(
            constitution_id=result.constitution_id,
            version=version.version,
            cap_micro_usdc=version.cap_micro_usdc,
            threshold_micro_usdc=version.threshold_micro_usdc,
            require_signature_for_new_payee=version.require_signature_for_new_payee,
            content_hash=version.content_hash,
            status=version.status,
            events=result.events,
        )

    @router.post(
        "/households/{household_id}/payees",
        response_model=PayeeResponse,
        status_code=201,
        dependencies=[Depends(require_scope("mandate:write"))],
        summary="Register a payee with a verified address and digest (FR-004)",
    )
    async def register_payee(
        household_id: str, body: RegisterPayeeRequest, request: Request
    ) -> PayeeResponse:
        require_owner_proof(body.owner_proof)
        result = await _services(request)["register_payee"].execute(  # type: ignore[attr-defined]
            RegisterPayeeCommand(
                household_id=household_id,
                name=body.name,
                address=body.address,
                routing_scheme=body.routing_scheme,
                routing_account_number=body.routing_account_number,
                routing_number=body.routing_number,
                owner_proof=body.owner_proof,
            )
        )
        payee = result.payee
        return PayeeResponse(
            payee_id=payee.payee_id,
            name=payee.name,
            address=payee.address,
            verified_digest=payee.verified_digest,
            status=payee.status,
            events=result.events,
        )

    @router.post(
        "/payees/{payee_id}/presented-digest",
        response_model=PayeeResponse,
        dependencies=[Depends(require_scope("billing:propose"))],
        summary="Compare an invoice's presented digest (FR-005). Mismatch quarantines.",
    )
    async def review_presented_digest(
        payee_id: str, body: PresentedDigestRequest, request: Request
    ) -> PayeeResponse:
        result = await _services(request)["quarantine_payee"].execute(  # type: ignore[attr-defined]
            ReviewPresentedDigestCommand(
                payee_id=payee_id,
                presented_digest=body.presented_digest,
                invoice_id=body.invoice_id,
            )
        )
        payee = result.payee
        return PayeeResponse(
            payee_id=payee.payee_id,
            name=payee.name,
            address=payee.address,
            verified_digest=payee.verified_digest,
            status=payee.status,
            events=result.events,
            quarantined=result.quarantined,
        )

    @router.post(
        "/payees/{payee_id}/reapprove",
        response_model=PayeeResponse,
        dependencies=[Depends(require_scope("mandate:write"))],
        summary="Owner re-approves new bank details (FR-005)",
    )
    async def reapprove(payee_id: str, body: ReapproveRequest, request: Request) -> PayeeResponse:
        require_owner_proof(body.owner_proof)
        result = await _services(request)["reapprove_payee"].execute(  # type: ignore[attr-defined]
            ReapprovePayeeDigestCommand(
                payee_id=payee_id,
                routing_scheme=body.routing_scheme,
                routing_account_number=body.routing_account_number,
                routing_number=body.routing_number,
                owner_proof=body.owner_proof,
            )
        )
        payee = result.payee
        return PayeeResponse(
            payee_id=payee.payee_id,
            name=payee.name,
            address=payee.address,
            verified_digest=payee.verified_digest,
            status=payee.status,
            events=result.events,
        )

    @router.post(
        "/payees/{payee_id}/freeze",
        response_model=PayeeResponse,
        dependencies=[Depends(require_scope("mandate:write"))],
        summary="Owner freezes a payee (FR-006)",
    )
    async def freeze_payee(payee_id: str, request: Request) -> PayeeResponse:
        result = await _services(request)["freeze_payee"].execute(  # type: ignore[attr-defined]
            FreezePayeeCommand(payee_id=payee_id)
        )
        payee = result.payee
        return PayeeResponse(
            payee_id=payee.payee_id,
            name=payee.name,
            address=payee.address,
            verified_digest=payee.verified_digest,
            status=payee.status,
            events=result.events,
        )

    @router.get(
        "/payees/{payee_id}/eligibility",
        response_model=EligibilityResponse,
        dependencies=[Depends(require_scope("authority:evaluate"))],
        summary="Read-through eligibility for dispatch-time checks (FR-012)",
    )
    async def eligibility(payee_id: str, request: Request) -> EligibilityResponse:
        view = await _services(request)["eligibility"].eligibility_of(payee_id)  # type: ignore[attr-defined]
        return EligibilityResponse(verdict=view.verdict, reason=view.reason)

    return router


def install(app: object) -> None:
    """Compose the Mandate context into a FastAPI app (called by the deployable's app.py)."""
    app.include_router(build_router())  # type: ignore[attr-defined]

    def _start(application: object) -> None:
        application.state.mandate_services = build_services(  # type: ignore[attr-defined]
            application.state.session_factory  # type: ignore[attr-defined]
        )

    app.state.startup_hooks.append(_start)  # type: ignore[attr-defined]


def build_services(session_factory: object) -> dict[str, object]:
    """Build one instance of every catalog service for the app shell."""
    return {
        "create_mandate": CreateMandateService(session_factory),  # type: ignore[arg-type]
        "publish_version": PublishConstitutionVersionService(session_factory),  # type: ignore[arg-type]
        "register_payee": RegisterPayeeService(session_factory),  # type: ignore[arg-type]
        "quarantine_payee": QuarantinePayeeService(session_factory),  # type: ignore[arg-type]
        "reapprove_payee": ReapprovePayeeDigestService(session_factory),  # type: ignore[arg-type]
        "freeze_payee": FreezePayeeService(session_factory),  # type: ignore[arg-type]
        "eligibility": EligibilityReaderService(session_factory),  # type: ignore[arg-type]
    }
