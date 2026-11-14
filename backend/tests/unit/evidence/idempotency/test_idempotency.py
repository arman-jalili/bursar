"""E-4 — the same `event_id` delivered three times produces exactly one envelope.

Canonical: docs/contracts/evidence-contract-freeze.md §1
Reference: .pi/architecture/modules/evidence.md#acceptance-criteria

At-least-once delivery means duplicates are normal. The claim on `(event_id, handler)` happens before
the append, so a replay is a no-op rather than a second proof of the same fact. Fails today from
`SealEvidence.execute`.
"""

from __future__ import annotations

from src.authority.domain.events import PaymentAllowed
from src.evidence.application.dto import SealEvidenceCommand
from src.evidence.application.services import SealEvidence

from tests.unit.evidence._fixtures import (
    FakeAnchorGateway,
    FakeEnvelopeStore,
    FakeProcessedEvents,
    HmacSigner,
    StaticPolicy,
)


class TestIdempotency:
    async def test_the_same_event_delivered_three_times_is_sealed_once(self) -> None:
        """E-4: the first delivery seals; the second and third report a duplicate and append nothing."""
        store = FakeEnvelopeStore()
        service = SealEvidence(
            envelopes=store,
            processed=FakeProcessedEvents(),
            signer=HmacSigner("operator-held-test-key"),
            policy=StaticPolicy(),
            anchors=FakeAnchorGateway(),
        )
        event = PaymentAllowed(
            intent_id="intent-1", amount_micro_usdc=42_500_000, reservation_id="res-1"
        )
        command = SealEvidenceCommand(event=event, actor="authority")

        results = [await service.execute(command) for _ in range(3)]

        assert len(store.appended) == 1
        assert results[0].sealed is True
        assert results[1].duplicate is True
        assert results[2].duplicate is True
        assert results[0].event_id == event.event_id
