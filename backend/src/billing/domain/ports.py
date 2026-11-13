"""Billing domain ports — the narrow interfaces the application services depend on (frozen).

Canonical: .pi/architecture/modules/billing.md#components
Reference: docs/contracts/billing-contract-freeze.md §2.9

Two ports, and each exists to keep a foreign concern out of the domain:

`DigestReviewPort` — Billing reports the digest *as presented on the document* to Mandate, which
compares it with the payee's verified baseline and quarantines on mismatch (scenario 2). Billing's
half is deliberately passive: it records the fact and never decides eligibility. The port returns a
view, not a policy, so B-4 ("never used for routing") stays structural — the only thing Billing can
do with the answer is store it / let Mandate act.

`InvoiceDocumentParser` — turns a raw document (a fixture byte string in the hackathon) into the
normalized mapping that `InvoiceHash` hashes (B-3). PDF/OCR extraction is a stretch item and must
never be reachable from the aggregate: the hash is over normalized fields, not over a parser's mood.

Ports are Protocols, not ABCs, for the same reason as Authority's upstream ports: the domain only
needs the shape, and an adapter (Mandate HTTP, fixture loader) lives in `infrastructure/` or
`interfaces/`. Neither port carries transaction control — the unit of work belongs to the
application layer (ADR-002).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from src.mandate.domain.values import BankDigest

__all__ = ["DigestReview", "DigestReviewPort", "InvoiceDocumentParser"]


@dataclass(frozen=True, slots=True)
class DigestReview:
    """Mandate's verdict on one presented digest (B-4).

    `matches` is a comparison of digests — not routing details — so the raw account number never
    travels back to Billing. `quarantined` is Mandate's fact, not Billing's decision: Billing stores
    it, and the refusal itself happens downstream.
    """

    payee_id: str
    matches: bool
    quarantined: bool
    verified_digest: str = ""
    status: str = ""


class DigestReviewPort(Protocol):
    """Anti-corruption port: hand a presented digest to Mandate for comparison.

    The adapter is the only place that knows about Mandate's HTTP surface; the Billing domain only
    knows that a review happened. Implementations MUST NOT cache the payee's verified digest — the
    comparison has to be against the baseline in force now (P-2).
    """

    async def review(
        self,
        *,
        invoice_id: str,
        payee_id: str,
        presented_digest: BankDigest,
    ) -> DigestReview:
        """Compare the document's digest with the payee's verified baseline.

        Returns:
            The review outcome. A mismatch is reported, never raised here: Billing must record the
            bill so the mismatch becomes evidence (scenario 2).

        Raises:
            ValidationError: the payee or digest is malformed.
            NotFoundError: the payee does not exist.
        """
        ...


class InvoiceDocumentParser(Protocol):
    """Normalize an invoice document into the field set that `InvoiceHash` hashes (B-3)."""

    def parse(self, raw: bytes) -> Mapping[str, object]:
        """Return a canonical, hash-ready document.

        Raises:
            ValidationError: the document is empty or cannot be parsed.
        """
        ...
