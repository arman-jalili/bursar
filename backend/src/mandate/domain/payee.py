"""Payee — the eligibility gate. This is where the bank-detail-change scam dies.

Canonical: .pi/architecture/modules/mandate.md#aggregate-payee
Reference: .pi/architecture/decisions/ADR-007-compliance-engine-architecture.md

Contract (v1) — aggregate root:

    P-1  only the owner may register a payee, with a verified address + digest; it starts NEW
    P-2  a presented digest differing from `verified_digest` sets QUARANTINED and NEVER rewrites
         `address`
    P-3  only an owner signature may clear QUARANTINED
    P-4  FROZEN is absorbing relative to quarantine: no downgrade, and digest review is a no-op
    P-5  `verified_digest` changes only through `reapprove()`
    P-6  `eligibility()` is derived from status, never settable

The single most important line in this file is the one that is *absent*: `review_presented_digest`
never assigns to `self.address`. The scam only works if the app "helpfully" updates the destination;
P-2 makes that assignment impossible rather than merely discouraged.

Bodies are TODO: `payee-review-presented-digest` and `payee-reapprove` items fill them in.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.mandate.domain.ids import HouseholdId, PayeeId
from src.mandate.domain.ports import OwnerSignatureProof
from src.mandate.domain.values import (
    BankDigest,
    Eligibility,
    PartyRef,
    PayeeAddress,
    PayeeName,
    PayeeStatus,
)
from src.shared.domain.aggregate import AggregateRoot

__all__ = ["Payee"]


@dataclass(eq=False)
class Payee(AggregateRoot):
    """A registered biller with a verified address, verified digest and eligibility status."""

    id: PayeeId
    household_id: HouseholdId
    name: PayeeName
    address: PayeeAddress
    verified_digest: BankDigest
    status: PayeeStatus

    @classmethod
    def register(
        cls,
        *,
        household_id: HouseholdId,
        name: PayeeName,
        address: PayeeAddress,
        digest: BankDigest,
        actor: PartyRef,
        proof: OwnerSignatureProof,
    ) -> Payee:
        """Register a payee as `NEW` (P-1). Emits `PayeeRegistered`.

        Raises:
            OwnerActionRequired: non-owner actor (H-3/P-1 → HTTP 403).
            OwnerProofInvalid: signature does not cover (digest, address).
        """
        raise NotImplementedError("Payee.register — see module doc AC #9")

    def review_presented_digest(self, presented: BankDigest, *, invoice_id: str = "") -> None:
        """Compare an invoice's presented digest with the verified one (P-2, P-4, AC #3).

        On mismatch: status becomes `QUARANTINED` and both `PayeeDigestChanged` and
        `PayeeQuarantined` are recorded. On a frozen payee this is a complete no-op (P-4).
        **`address` is never touched** — see the module doc, scenario 2.
        """
        raise NotImplementedError("Payee.review_presented_digest — see module doc AC #3")

    def reapprove(
        self, new_digest: BankDigest, *, actor: PartyRef, proof: OwnerSignatureProof
    ) -> None:
        """Owner accepts new bank details: replace the baseline, return to ELIGIBLE (P-3, P-5).

        Raises:
            OwnerActionRequired: non-owner actor.
            OwnerProofInvalid: signature does not cover (payee_id, new_digest) — status unchanged.
        """
        raise NotImplementedError("Payee.reapprove — see module doc AC #4")

    def freeze(self, actor: PartyRef) -> None:
        """Owner suspends the payee entirely (P-4, FR-006). Emits `PayeeFrozen`."""
        raise NotImplementedError("Payee.freeze — see module doc AC #5")

    def unfreeze(self, *, actor: PartyRef, proof: OwnerSignatureProof) -> None:
        """Return a frozen payee to ELIGIBLE. Owner-signed; supporting operation, not in the catalog."""
        raise NotImplementedError("Payee.unfreeze — supporting operation")

    def eligibility(self, *, require_signature_for_new_payee: bool = True) -> Eligibility:
        """The derived verdict Authority consumes (P-6, FR-012, AC #11).

        NEW → escalate("new_payee") · ELIGIBLE → allow()
        QUARANTINED → deny("payee_quarantined") · FROZEN → deny("payee_frozen")
        """
        raise NotImplementedError("Payee.eligibility — see module doc AC #11")
