"""E-4 / E-5 — the persistence contract claims before it appends.

Canonical: docs/contracts/evidence-contract-freeze.md §1
Reference: docs/architecture/modules/evidence.md#persistence-contract

The idempotency key `(event_id, handler)` is stored by `ProcessedEventRepository`, and the envelope is
only appended when that claim is new. A replay must not create a second row — the table is append-only
and the proof is one-per-fact. Fails today from `SealEvidence.execute`.
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


class TestPersistenceContract:
    async def test_a_replayed_delivery_appends_no_second_envelope(self) -> None:
        """E-4/E-5: the store grows by one regardless of how many times the delivery is repeated."""
        store = FakeEnvelopeStore()
        service = SealEvidence(
            envelopes=store,
            processed=FakeProcessedEvents(),
            signer=HmacSigner("operator-held-test-key"),
            policy=StaticPolicy(),
            anchors=FakeAnchorGateway(),
        )
        event = PaymentAllowed(
            intent_id="intent-7", amount_micro_usdc=42_500_000, reservation_id="res-7"
        )
        command = SealEvidenceCommand(event=event, actor="authority")

        await service.execute(command)
        await service.execute(command)

        assert len(store.appended) == 1
