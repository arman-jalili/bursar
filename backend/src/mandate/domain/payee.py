"""Payee — the eligibility gate. This is where the bank-detail-change scam dies.

Canonical: docs/architecture/modules/mandate.md#aggregate-payee
Reference: docs/architecture/decisions/ADR-007-compliance-engine-architecture.md

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

Every transition is guarded here, and there is no `set_status`: an illegal state is unrepresentable
rather than merely discouraged.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.mandate.domain.errors import OwnerActionRequired, OwnerProofInvalid
from src.mandate.domain.events import (
    PayeeDigestChanged,
    PayeeFrozen,
    PayeeQuarantined,
    PayeeReapproved,
    PayeeRegistered,
)
from src.mandate.domain.ids import HouseholdId, PayeeId, new_id
from src.mandate.domain.ports import OwnerSignatureProof
from src.mandate.domain.values import (
    BankDigest,
    Eligibility,
    PartyRef,
    PayeeAddress,
    PayeeName,
    PayeeStatus,
    ReasonCode,
    Role,
)
from src.shared.domain.aggregate import AggregateRoot
from src.shared.domain.event import utcnow

__all__ = ["Payee"]


def _require_owner(actor: PartyRef) -> None:
    """H-3 / P-1 / P-3: every state change here is an owner act; the agent is refused at the door."""
    if actor.role is not Role.OWNER:
        raise OwnerActionRequired(role=actor.role.value)


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
        _require_owner(actor)
        if not proof.signs(digest, address):
            raise OwnerProofInvalid(
                "the owner signature does not cover this payee's digest and address"
            )
        payee = cls(
            id=PayeeId(new_id()),
            household_id=household_id,
            name=name,
            address=address,
            verified_digest=digest,
            status=PayeeStatus.NEW,
        )
        payee.record(
            PayeeRegistered(
                aggregate_id=payee.id,
                payee_id=payee.id,
                name=name.value,
                address=address.value,
                digest=digest.hash,
            )
        )
        return payee

    def review_presented_digest(self, presented: BankDigest, *, invoice_id: str = "") -> None:
        """Compare an invoice's presented digest with the verified one (P-2, P-4, AC #3).

        On mismatch: status becomes `QUARANTINED` and both `PayeeDigestChanged` and
        `PayeeQuarantined` are recorded. On a frozen payee this is a complete no-op (P-4).
        **`address` is never touched** — see the module doc, scenario 2.
        """
        if self.status is PayeeStatus.FROZEN:
            return  # P-4: freeze dominates; an automatic transition must not soften it
        if presented.matches(self.verified_digest):
            return
        self.status = PayeeStatus.QUARANTINED
        self.record(
            PayeeDigestChanged(
                aggregate_id=self.id,
                payee_id=self.id,
                presented_digest=presented.hash,
                verified_digest=self.verified_digest.hash,
                invoice_id=invoice_id,
            )
        )
        self.record(
            PayeeQuarantined(
                aggregate_id=self.id,
                payee_id=self.id,
                reason=ReasonCode.DIGEST_MISMATCH.value,
                at_iso=utcnow().isoformat(),
            )
        )
        # `self.address` is deliberately untouched: the money is stopped, not redirected.

    def reapprove(
        self, new_digest: BankDigest, *, actor: PartyRef, proof: OwnerSignatureProof
    ) -> None:
        """Owner accepts new bank details: replace the baseline, return to ELIGIBLE (P-3, P-5).

        Raises:
            OwnerActionRequired: non-owner actor.
            OwnerProofInvalid: signature does not cover (payee_id, new_digest) — status unchanged.
        """
        _require_owner(actor)
        if not proof.signs(self.id, new_digest):
            raise OwnerProofInvalid("the owner signature does not cover the new bank digest")
        previous = self.verified_digest
        self.verified_digest = new_digest
        self.status = PayeeStatus.ELIGIBLE
        self.record(
            PayeeReapproved(
                aggregate_id=self.id,
                payee_id=self.id,
                previous_digest=previous.hash,
                new_digest=new_digest.hash,
                actor_id=actor.id,
            )
        )

    def freeze(self, actor: PartyRef) -> None:
        """Owner suspends the payee entirely (P-4, FR-006). Emits `PayeeFrozen`.

        `FROZEN` is terminal within a mandate: the state diagram has no unfreeze transition, because
        a resumed relationship is a re-registration (with fresh owner proof), not a state flip.
        """
        _require_owner(actor)
        if self.status is PayeeStatus.FROZEN:
            return  # idempotent: re-freezing an already frozen payee changes nothing
        self.status = PayeeStatus.FROZEN
        self.record(
            PayeeFrozen(
                aggregate_id=self.id,
                payee_id=self.id,
                actor_id=actor.id,
                at_iso=utcnow().isoformat(),
            )
        )

    def eligibility(self, *, require_signature_for_new_payee: bool = True) -> Eligibility:
        """The derived verdict Authority consumes (P-6, FR-012, AC #11).

        NEW → escalate("new_payee") · ELIGIBLE → allow()
        QUARANTINED → deny("payee_quarantined") · FROZEN → deny("payee_frozen")
        """
        if self.status is PayeeStatus.ELIGIBLE:
            return Eligibility.allow()
        if self.status is PayeeStatus.NEW:
            if require_signature_for_new_payee:
                return Eligibility.escalate(ReasonCode.NEW_PAYEE.value)
            return Eligibility.allow()
        if self.status is PayeeStatus.QUARANTINED:
            return Eligibility.deny(ReasonCode.PAYEE_QUARANTINED.value)
        return Eligibility.deny(ReasonCode.PAYEE_FROZEN.value)
