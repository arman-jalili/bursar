"""Concrete Evidence application services — one unit of work each (ADR-002).

Canonical: .pi/architecture/modules/evidence.md#application-services
Reference: docs/contracts/evidence-contract-freeze.md §2.7

The frozen use cases in `application/services.py` take ports; these classes are the composition
wrapper that gives them a session, adapters and a transaction. Each method follows the same shape:

1. open exactly one `session_scope`,
2. build the SQLAlchemy adapters on that session,
3. call one frozen use case,
4. return a read-model DTO.

Read paths (`ListEnvelopes`, `GetEnvelope`, `GetAnchor`) are operational, below the use-case catalog
the module doc defines. They still live here rather than in the router so the HTTP layer stays a thin
translation of a result into JSON.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.evidence.application.dto import (
    EnvelopeView,
    SealEvidenceCommand,
    SealEvidenceResult,
    VerifyEvidenceCommand,
    VerifyEvidenceResult,
)
from src.evidence.application.services import SealEvidence, VerifyEvidence, WitnessReport
from src.evidence.domain.errors import EnvelopeNotFound, NotFoundError
from src.evidence.domain.evidence_envelope import EvidenceEnvelope
from src.evidence.domain.ids import EnvelopeId
from src.evidence.domain.ports import AnchorGateway, AnchorPolicy, EnvelopeSigner
from src.evidence.infrastructure.anchor import ConfiguredAnchorPolicy, SqlAnchorGateway
from src.evidence.infrastructure.expected_events import SqlExpectedEvents
from src.evidence.infrastructure.repositories import (
    SqlAnchorRepository,
    SqlEnvelopeRepository,
    SqlProcessedEventRepository,
)
from src.evidence.infrastructure.signer import HmacSigner
from src.shared.application.unit_of_work import session_scope
from src.shared.infrastructure.config import Settings

__all__ = [
    "EvidenceServices",
    "GetAnchorService",
    "GetEnvelopeService",
    "ListEnvelopesService",
    "SealEvidenceService",
    "VerifyEvidenceService",
    "WitnessReportService",
    "build_services",
]


def _anchor_gateway(session: AsyncSession, *, chain_id: int) -> AnchorGateway:
    return SqlAnchorGateway(SqlAnchorRepository(session), chain_id=chain_id)


def _view(envelope: EvidenceEnvelope, *, anchor_tx: str | None, full: bool) -> EnvelopeView:
    return EnvelopeView(
        envelope_id=str(envelope.id),
        event_type=envelope.event_type,
        subject_intent_id=envelope.subject_intent_id,
        subject_invoice_id=envelope.subject_invoice_id,
        subject_payee_id=envelope.subject_payee_id,
        constitution_version=envelope.constitution_version,
        actor=envelope.actor,
        occurred_at=envelope.occurred_at,
        hmac=envelope.hmac,
        previous_hash=envelope.previous_hash,
        anchor_mode=envelope.anchor_mode,
        envelope_hash=envelope.hash().value,
        anchor_tx=anchor_tx,
        payload=dict(envelope.payload) if full else None,
    )


@dataclass(slots=True)
class SealEvidenceService:
    """FR-022 — seal one delivered fact in its own transaction."""

    session_factory: async_sessionmaker[AsyncSession]
    signer: EnvelopeSigner
    policy: AnchorPolicy
    chain_id: int

    async def execute(self, command: SealEvidenceCommand) -> SealEvidenceResult:
        async with session_scope(self.session_factory) as session:
            use_case = SealEvidence(
                envelopes=SqlEnvelopeRepository(session),
                processed=SqlProcessedEventRepository(session),
                signer=self.signer,
                policy=self.policy,
                anchors=_anchor_gateway(session, chain_id=self.chain_id),
            )
            return await use_case.execute(command)


@dataclass(slots=True)
class VerifyEvidenceService:
    """FR-023 — re-verify one envelope and name the failure."""

    session_factory: async_sessionmaker[AsyncSession]
    signer: EnvelopeSigner

    async def execute(self, command: VerifyEvidenceCommand) -> VerifyEvidenceResult:
        async with session_scope(self.session_factory) as session:
            use_case = VerifyEvidence(
                envelopes=SqlEnvelopeRepository(session),
                signer=self.signer,
                anchors=_anchor_gateway(session, chain_id=0),
            )
            return await use_case.execute(command)


@dataclass(slots=True)
class ListEnvelopesService:
    """Operational read model for `GET /v1/evidence`."""

    session_factory: async_sessionmaker[AsyncSession]

    async def execute(
        self,
        *,
        intent_id: str | None = None,
        invoice_id: str | None = None,
        event_type: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
        full: bool = False,
    ) -> tuple[Sequence[EnvelopeView], str | None]:
        async with session_scope(self.session_factory) as session:
            envelopes = await SqlEnvelopeRepository(session).list_for_subject(
                intent_id=intent_id,
                invoice_id=invoice_id,
                limit=limit + 1,
            )
            if event_type:
                envelopes = [e for e in envelopes if e.event_type == event_type]
            if cursor:
                envelopes = [e for e in envelopes if str(e.id) > cursor]

            page = list(envelopes[:limit])
            anchors = SqlAnchorRepository(session)
            views: list[EnvelopeView] = []
            for envelope in page:
                anchor = await anchors.find_for_envelope(envelope.hash())
                views.append(
                    _view(
                        envelope,
                        anchor_tx=anchor.anchor_tx if anchor else None,
                        full=full,
                    )
                )
            next_cursor = str(page[-1].id) if len(envelopes) > limit and page else None
            return views, next_cursor


@dataclass(slots=True)
class GetEnvelopeService:
    """Operational read model for `GET /v1/evidence/{id}`."""

    session_factory: async_sessionmaker[AsyncSession]

    async def execute(self, envelope_id: str, *, full: bool = False) -> EnvelopeView:
        async with session_scope(self.session_factory) as session:
            envelope = await SqlEnvelopeRepository(session).find_by_id(EnvelopeId(envelope_id))
            if envelope is None:
                raise EnvelopeNotFound(envelope_id)
            anchor = await SqlAnchorRepository(session).find_for_envelope(envelope.hash())
            return _view(envelope, anchor_tx=anchor.anchor_tx if anchor else None, full=full)


@dataclass(slots=True)
class GetAnchorService:
    """Operational read model for `GET /v1/evidence/{id}/anchor`."""

    session_factory: async_sessionmaker[AsyncSession]

    async def execute(self, envelope_id: str) -> tuple[str, int, int]:
        async with session_scope(self.session_factory) as session:
            envelope = await SqlEnvelopeRepository(session).find_by_id(EnvelopeId(envelope_id))
            if envelope is None:
                raise EnvelopeNotFound(envelope_id)
            anchor = await SqlAnchorRepository(session).find_for_envelope(envelope.hash())
            if anchor is None:
                raise NotFoundError(
                    "That envelope has no anchor yet.",
                    envelope_id=envelope_id,
                )
            return anchor.anchor_tx, anchor.block_number, anchor.chain_id


@dataclass(slots=True)
class WitnessReportService:
    """Operational read model: expected facts with no envelope (E-10)."""

    session_factory: async_sessionmaker[AsyncSession]

    async def execute(self, *, since: datetime, until: datetime) -> tuple[str, ...]:
        async with session_scope(self.session_factory) as session:
            use_case = WitnessReport(
                expected=SqlExpectedEvents(session),
                processed=SqlProcessedEventRepository(session),
            )
            return await use_case.missing(since=since, until=until)


@dataclass(frozen=True, slots=True)
class EvidenceServices:
    """The set of services the HTTP transport and subscriber both dial."""

    seal: SealEvidenceService
    verify: VerifyEvidenceService
    list_envelopes: ListEnvelopesService
    get_envelope: GetEnvelopeService
    get_anchor: GetAnchorService
    witness_report: WitnessReportService


def build_services(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> EvidenceServices:
    """Compose the Evidence services once per application (composition root calls this)."""
    signer = HmacSigner.from_settings(settings)
    policy = ConfiguredAnchorPolicy.from_settings(settings)
    return EvidenceServices(
        seal=SealEvidenceService(
            session_factory=session_factory,
            signer=signer,
            policy=policy,
            chain_id=settings.chain_id,
        ),
        verify=VerifyEvidenceService(session_factory=session_factory, signer=signer),
        list_envelopes=ListEnvelopesService(session_factory=session_factory),
        get_envelope=GetEnvelopeService(session_factory=session_factory),
        get_anchor=GetAnchorService(session_factory=session_factory),
        witness_report=WitnessReportService(session_factory=session_factory),
    )
