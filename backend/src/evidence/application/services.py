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
from datetime import datetime

from src.evidence.application.dto import (
    SealEvidenceCommand,
    SealEvidenceResult,
    VerifyEvidenceCommand,
    VerifyEvidenceResult,
)
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
        raise NotImplementedError("E-2 — see module doc")


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
        raise NotImplementedError("E-6 — see module doc")


@dataclass(slots=True)
class WitnessReport:
    """Operational read model: which expected facts have no envelope (E-10)."""

    expected: ExpectedEventsPort
    processed: ProcessedEventRepository

    async def missing(self, *, since: datetime, until: datetime) -> tuple[str, ...]:
        """Return the `event_id`s that should exist but were never sealed."""
        raise NotImplementedError("E-10 — see module doc")
