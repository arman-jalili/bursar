"""The Evidence HTTP router — concrete, registered once in the app shell.

Canonical: docs/architecture/modules/evidence.md#api-endpoints
Reference: docs/contracts/evidence-contract-freeze.md §2.9

Thin on purpose: translate a query into a read-model call, map the result back. No module rule lives
here. Verification failures are *not* caught: `HmacMismatch` and `AnchorMismatch` extend the shared
`RefusalError`, so the ADR-004 handler renders them as `409` with `result`/`field`/`anchor_tx` in
`details` — the console never receives a bespoke Evidence error shape.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from src.evidence.application.dto import EnvelopeView, VerifyEvidenceCommand
from src.evidence.application.services_impl import EvidenceServices
from src.evidence.interfaces.http.deps import require_scope
from src.evidence.interfaces.http.schemas import (
    AnchorResponse,
    EnvelopeListResponse,
    EnvelopeResponse,
    VerifyResponse,
)

__all__ = ["build_router", "install"]

READ = "evidence:read"
CONSOLE = "console:read"


def _services(request: Request) -> EvidenceServices:
    services: EvidenceServices = request.app.state.evidence_services
    return services


def _envelope_response(view: EnvelopeView) -> EnvelopeResponse:
    return EnvelopeResponse(
        envelope_id=view.envelope_id,
        event_type=view.event_type,
        subject_intent_id=view.subject_intent_id,
        subject_invoice_id=view.subject_invoice_id,
        subject_payee_id=view.subject_payee_id,
        constitution_version=view.constitution_version,
        actor=view.actor,
        occurred_at=view.occurred_at,
        hmac=view.hmac,
        previous_hash=view.previous_hash,
        anchor_mode=view.anchor_mode,
        envelope_hash=view.envelope_hash,
        anchor_tx=view.anchor_tx,
        payload=dict(view.payload) if view.payload is not None else None,
    )


def build_router() -> APIRouter:
    """Build a fresh router (tests build many apps; re-decorating one shared router duplicates routes)."""
    router = APIRouter(prefix="/v1", tags=["evidence"])

    @router.get(
        "/evidence",
        response_model=EnvelopeListResponse,
        dependencies=[Depends(require_scope(READ))],
        summary="List envelopes (newest page by cursor; payload only with ?full=1)",
    )
    async def list_envelopes(
        request: Request,
        intent_id: str | None = None,
        invoice_id: str | None = None,
        event_type: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
        full: bool = False,
    ) -> EnvelopeListResponse:
        views, next_cursor = await _services(request).list_envelopes.execute(
            intent_id=intent_id,
            invoice_id=invoice_id,
            event_type=event_type,
            cursor=cursor,
            limit=limit,
            full=full,
        )
        return EnvelopeListResponse(
            items=[_envelope_response(view) for view in views],
            next_cursor=next_cursor,
        )

    @router.get(
        "/evidence/{envelope_id}/verify",
        response_model=VerifyResponse,
        dependencies=[Depends(require_scope(CONSOLE))],
        summary="Re-verify an envelope (scenario 7): VERIFIED, UNANCHORED or 409 on tampering",
    )
    async def verify_envelope(envelope_id: str, request: Request) -> VerifyResponse:
        result = await _services(request).verify.execute(
            VerifyEvidenceCommand(envelope_id=envelope_id)
        )
        return VerifyResponse(
            result=result.result.value,
            field=result.failing_field,
            anchor_tx=result.anchor_tx,
        )

    @router.get(
        "/evidence/{envelope_id}/anchor",
        response_model=AnchorResponse,
        dependencies=[Depends(require_scope(READ))],
        summary="Read the on-chain anchor for an envelope",
    )
    async def get_anchor(envelope_id: str, request: Request) -> AnchorResponse:
        anchor_tx, block_number, chain_id = await _services(request).get_anchor.execute(envelope_id)
        return AnchorResponse(anchor_tx=anchor_tx, block_number=block_number, chain_id=chain_id)

    @router.get(
        "/evidence/{envelope_id}",
        response_model=EnvelopeResponse,
        dependencies=[Depends(require_scope(READ))],
        summary="Read one envelope (payload only with ?full=1)",
    )
    async def get_envelope(
        envelope_id: str, request: Request, full: bool = False
    ) -> EnvelopeResponse:
        view = await _services(request).get_envelope.execute(envelope_id, full=full)
        return _envelope_response(view)

    return router


def install(app: object) -> None:
    """Compose Evidence into a FastAPI app (called by the deployable's composition root)."""
    app.include_router(build_router())  # type: ignore[attr-defined]

    def _start(application: object) -> None:
        from src.evidence.application.services_impl import build_services
        from src.evidence.interfaces.subscriber import SealEventSubscriber

        services = build_services(
            application.state.session_factory,  # type: ignore[attr-defined]
            application.state.settings,  # type: ignore[attr-defined]
        )
        application.state.evidence_services = services  # type: ignore[attr-defined]
        application.state.evidence_subscriber = SealEventSubscriber(services.seal)  # type: ignore[attr-defined]

    app.state.startup_hooks.append(_start)  # type: ignore[attr-defined]
