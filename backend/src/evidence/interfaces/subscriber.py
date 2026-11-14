"""The Evidence event subscriber — the runtime entry path that seals publisher facts.

Canonical: .pi/architecture/decisions/ADR-003-cross-context-communication.md
Reference: .pi/architecture/modules/evidence.md#components

ADR-003 delivers events from Authority, Billing, Settlement and Mandate at least once. The
subscriber's whole job is to hand one fact to `SealEvidence` and return its result; it never raises
for a witness outage (E-10) and it never edits the publisher's event (the envelope is a wrapper).

Delivery wiring (`outbox → this subscriber`) is the deployable's concern. The class is installed on
`app.state.evidence_subscriber` by the composition root so any publisher worker can dial it without
importing Evidence's application layer.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.evidence.application.dto import SealEvidenceCommand, SealEvidenceResult
from src.evidence.application.services_impl import SealEvidenceService
from src.shared.domain.event import DomainEvent
from src.shared.infrastructure.logging import get_logger

__all__ = ["SealEventSubscriber"]

logger = get_logger(__name__)


@dataclass(slots=True)
class SealEventSubscriber:
    """Idempotent subscriber: one delivery → at most one envelope (E-2, E-4)."""

    seal: SealEvidenceService

    async def handle(self, event: DomainEvent, *, actor: str) -> SealEvidenceResult:
        """Seal one delivered fact. A duplicate/replay returns `duplicate=True`."""
        result = await self.seal.execute(SealEvidenceCommand(event=event, actor=actor))
        if result.witness_gap:
            # Operational gap only: the publisher has already moved on (E-10). No payload, no key.
            logger.warning(
                "evidence.witness.gap",
                extra={
                    "event_id": result.event_id,
                    "event_type": event.event_name,
                    "witness_gap": result.witness_gap,
                },
            )
        elif result.duplicate:
            logger.info(
                "evidence.seal.duplicate",
                extra={"event_id": result.event_id, "event_type": event.event_name},
            )
        else:
            logger.info(
                "evidence.envelope.sealed",
                extra={
                    "event_id": result.event_id,
                    "event_type": event.event_name,
                    "envelope_id": result.envelope_id,
                    "envelope_hash": result.envelope_hash,
                    "anchored": result.anchor_tx is not None,
                },
            )
        return result
