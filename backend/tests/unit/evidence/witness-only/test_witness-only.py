"""E-10 — stopping Evidence does not block dispatch; the failure is reported as a gap.

Canonical: docs/contracts/evidence-contract-freeze.md §1
Reference: docs/architecture/modules/evidence.md#description

Evidence is a witness, not a guard. A signer or anchor outage must not turn a payment into a failure:
the subscriber returns a result with `sealed=False` and a `witness_gap`, and the publisher carries on.
The gap is then findable through the ports (see `tests/unit/evidence/ports/`). Fails today from
`SealEvidence.execute`.
"""

from __future__ import annotations

from src.authority.domain.events import PaymentAllowed
from src.evidence.application.dto import SealEvidenceCommand
from src.evidence.application.services import SealEvidence

from tests.unit.evidence._fixtures import (
    FailingSigner,
    FakeAnchorGateway,
    FakeEnvelopeStore,
    FakeProcessedEvents,
    StaticPolicy,
)


class TestWitnessOnly:
    async def test_a_signing_outage_is_a_reported_gap_not_a_publisher_error(self) -> None:
        """E-10: the fact is not blocked; no envelope is written and the gap is named."""
        store = FakeEnvelopeStore()
        service = SealEvidence(
            envelopes=store,
            processed=FakeProcessedEvents(),
            signer=FailingSigner(),
            policy=StaticPolicy(),
            anchors=FakeAnchorGateway(),
        )
        event = PaymentAllowed(
            intent_id="intent-1", amount_micro_usdc=42_500_000, reservation_id="res-1"
        )

        result = await service.execute(SealEvidenceCommand(event=event, actor="authority"))

        assert result.sealed is False
        assert result.witness_gap is not None
        assert store.appended == []
