"""Evidence application services — the two catalog names, frozen (FR-022, FR-023).

Canonical: .pi/architecture/modules/evidence.md#application-services
Reference: docs/contracts/evidence-contract-freeze.md §2.7

    SealEvidence    FR-022   claim the delivery, seal one envelope, anchor its hash (E-2, E-4, E-10)
    VerifyEvidence  FR-023   recompute + compare, returning VERIFIED or the named failure (E-6 … E-8)

Names come from the exploration use-cases pass and are not negotiable: they are how the console, the
subscriber and the evidence trail refer to these use cases.

The services are dataclasses so the dependency set is part of the frozen signature, while `execute`
is still a stub. Phase B fills the body; it does not widen the ports or add a third use case.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from src.evidence.application.dto import (
    SealEvidenceCommand,
    SealEvidenceResult,
    VerifyEvidenceCommand,
    VerifyEvidenceResult,
)
from src.evidence.domain.anchor import Anchor
from src.evidence.domain.errors import (
    AnchoringUnavailable,
    EnvelopeNotFound,
    SigningUnavailable,
)
from src.evidence.domain.evidence_envelope import EvidenceEnvelope
from src.evidence.domain.ids import AnchorId, EnvelopeId, EventId
from src.evidence.domain.ports import (
    AnchorGateway,
    AnchorPolicy,
    EnvelopeSigner,
    ExpectedEventsPort,
)
from src.evidence.domain.repositories import (
    EnvelopeRepository,
    ProcessedEventRepository,
)

__all__ = ["SealEvidence", "VerifyEvidence", "WitnessReport"]

#: The handler name in the idempotency key `(event_id, handler)` (E-4).
SEAL_HANDLER = "seal"


@dataclass(slots=True)
class SealEvidence:
    """Seal every delivered fact — including refusals — exactly once (FR-022)."""

    envelopes: EnvelopeRepository
    processed: ProcessedEventRepository
    signer: EnvelopeSigner
    policy: AnchorPolicy
    anchors: AnchorGateway

    async def execute(self, command: SealEvidenceCommand) -> SealEvidenceResult:
        """Claim the delivery, build + append one envelope, then try to anchor it.

        The contract is idempotent on `(event_id, "seal")` (E-4) and **never raises** for a
        signing/anchoring failure: it returns `sealed=False` with a `witness_gap` so the publisher is
        not blocked (E-10). It still raises for a programming error (a malformed event payload).

        Raises:
            AppendOnlyViolation: the repository was asked to overwrite an envelope (E-5).
        """
        event = command.event
        anchor_mode = self.policy.mode_for(event.event_name) or command.anchor_mode

        # Seal before claiming: if the signer is down there is no envelope, so leaving a claim behind
        # would make every retry look like a duplicate and the fact would never be witnessed.
        try:
            envelope = EvidenceEnvelope.from_event(
                event,
                signer=self.signer,
                actor=command.actor,
                anchor_mode=anchor_mode,
            )
        except SigningUnavailable as exc:
            return SealEvidenceResult(
                envelope_id="",
                event_id=event.event_id,
                envelope_hash="",
                sealed=False,
                witness_gap=_gap("signing_unavailable", exc),
            )

        if not await self.processed.claim(EventId(event.event_id), SEAL_HANDLER):
            return SealEvidenceResult(
                envelope_id="",
                event_id=event.event_id,
                envelope_hash="",
                sealed=False,
                duplicate=True,
            )

        await self.envelopes.append(envelope)
        envelope_hash = envelope.hash()

        anchor_tx: str | None = None
        witness_gap: str | None = None
        try:
            receipt = await self.anchors.write_anchor(envelope_hash)
            anchor_tx = receipt.anchor_tx
        except AnchoringUnavailable as exc:
            # The fact is sealed; only its independent on-chain proof is behind. Reporting
            # `sealed=False` here would let an unanchored envelope look like it was never recorded.
            witness_gap = _gap("anchoring_unavailable", exc)

        return SealEvidenceResult(
            envelope_id=str(envelope.id),
            event_id=event.event_id,
            envelope_hash=envelope_hash.value,
            anchor_tx=anchor_tx,
            sealed=True,
            witness_gap=witness_gap,
        )


def _gap(kind: str, exc: Exception) -> str:
    """A compact, secret-free gap label for the witness report (E-9, E-10)."""
    detail = getattr(exc, "details", {}).get("detail", "")
    return f"{kind}: {detail}" if detail else kind


@dataclass(slots=True)
class VerifyEvidence:
    """Re-verify one envelope and name the failure (FR-023)."""

    envelopes: EnvelopeRepository
    signer: EnvelopeSigner
    anchors: AnchorGateway

    async def execute(self, command: VerifyEvidenceCommand) -> VerifyEvidenceResult:
        """Load the envelope, recompute the HMAC, compare the anchor.

        Raises:
            EnvelopeNotFound: no envelope with that id (E-6).
            HmacMismatch: the payload no longer matches its HMAC (E-7).
            AnchorMismatch: the anchor belongs to a different hash (E-8).
        """
        envelope = await self.envelopes.find_by_id(EnvelopeId(command.envelope_id))
        if envelope is None:
            raise EnvelopeNotFound(command.envelope_id)

        envelope_hash = envelope.hash()
        receipt = await self.anchors.read_anchor(envelope_hash)
        anchor = (
            None
            if receipt is None
            else Anchor(
                id=AnchorId(""),
                envelope_hash=envelope_hash,
                anchor_tx=receipt.anchor_tx,
                block_number=receipt.block_number,
                chain_id=receipt.chain_id,
                anchored_at=datetime.now(UTC),
            )
        )

        verification = envelope.verify(self.signer, anchor)
        return VerifyEvidenceResult(
            result=verification.result,
            failing_field=verification.failing_field,
            anchor_tx=verification.anchor_tx,
        )


@dataclass(slots=True)
class WitnessReport:
    """Operational read model: which expected facts have no envelope (E-10)."""

    expected: ExpectedEventsPort
    processed: ProcessedEventRepository

    async def missing(self, *, since: datetime, until: datetime) -> tuple[str, ...]:
        """Return the `event_id`s that should exist but were never sealed."""
        expected = await self.expected.expected(since=since, until=until)
        missing: list[str] = []
        for event in expected:
            if not await self.processed.is_processed(event.event_id, SEAL_HANDLER):
                missing.append(str(event.event_id))
        return tuple(missing)
