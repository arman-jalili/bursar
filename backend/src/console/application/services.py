"""The three catalogued projections (frozen) — read models, never rules.

Canonical: .pi/architecture/modules/console.md#application-services-catalog
Reference: docs/contracts/console-contract-freeze.md §2.7

    ProjectApprovalInbox   FR-024   pending signature requests + owner display reads
    ProjectPayerBills      FR-025   handled/settled bills in household language
    ProjectEvidence                 envelopes + the proxied verified/tampered verdict

No projection takes a session, a repository or a database handle: the console reads other contexts
through their ports. `ProjectApprovalInbox` also serves the payee list and constitution because the
module doc names three projections and a fourth class for two lookup tables would be ceremony.

Nothing business-shaped lives here even once Phase B lands — the console composes, it does not
decide (CON-09).
"""

from __future__ import annotations

from src.console.application.dto import (
    ApprovalInboxItem,
    ConstitutionReadModel,
    EvidenceReadModel,
    PayeeReadModel,
    PaymentReadModel,
    VerificationReadModel,
)
from src.console.application.ports import (
    ApprovalInboxPort,
    BillsPort,
    ConstitutionPort,
    DeterminationPort,
    EvidencePort,
    ReceiptPort,
)

__all__ = ["ProjectApprovalInbox", "ProjectEvidence", "ProjectPayerBills"]


class ProjectApprovalInbox:
    """Projection for the owner: pending signature requests with exact intent fields (FR-024)."""

    def __init__(
        self,
        approvals: ApprovalInboxPort,
        determinations: DeterminationPort,
        constitution: ConstitutionPort,
    ) -> None:
        self._approvals = approvals
        self._determinations = determinations
        self._constitution = constitution

    async def execute(self, owner_scope: str) -> tuple[ApprovalInboxItem, ...]:
        """Return the owner's pending approvals.

        Raises:
            FieldFidelityViolation: a field would be normalised on its way to the screen (CON-02).
            WhitelistViolation: upstream sent a key no owner whitelist names (CON-01).
        """
        raise NotImplementedError("CON-02 — see module doc")

    async def payees(self, owner_scope: str) -> tuple[PayeeReadModel, ...]:
        """Display-only payee list for the owner (CON-01)."""
        raise NotImplementedError("CON-01 — see module doc")

    async def constitution_version(self, owner_scope: str) -> ConstitutionReadModel:
        """Current cap/threshold/version for display; the console never publishes one (CON-01)."""
        raise NotImplementedError("CON-01 — see module doc")


class ProjectPayerBills:
    """Projection for the payer: handled and settled bills, in household language (FR-025)."""

    def __init__(self, bills: BillsPort, receipts: ReceiptPort) -> None:
        self._bills = bills
        self._receipts = receipts

    async def execute(self, scope: str) -> tuple[PaymentReadModel, ...]:
        """Return every bill visible to this payer scope.

        Raises:
            PayoutNotLabelled: a settled bill would be rendered without the demo label (CON-06).
            PayerVocabularyViolation: the resulting copy contains crypto vocabulary (CON-05).
        """
        raise NotImplementedError("CON-06 — see module doc")

    async def one(self, scope: str, invoice_id: str) -> PaymentReadModel:
        """Return one bill for the payer detail screen (CON-06)."""
        raise NotImplementedError("CON-06 — see module doc")


class ProjectEvidence:
    """Projection for the owner's evidence viewer: envelopes and the proxied verdict (CON-08)."""

    def __init__(self, evidence: EvidencePort) -> None:
        self._evidence = evidence

    async def envelopes(self, intent_id: str | None) -> tuple[EvidenceReadModel, ...]:
        """List envelopes; hashes and reason codes, never the payload by default (CON-01)."""
        raise NotImplementedError("CON-01 — see module doc")

    async def verify(self, envelope_id: str) -> VerificationReadModel:
        """Proxy Evidence's verdict so the toggle can show verified/tampered (CON-08).

        Raises:
            VerificationRefused: Evidence could not answer; no verdict is invented.
        """
        raise NotImplementedError("CON-08 — see module doc")
