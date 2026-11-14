"""The statutory determination policy — the frozen interface's implementation (A-5 … A-8).

Canonical: .pi/architecture/modules/authority.md#domain-services
Reference: docs/contracts/authority-contract-freeze.md §2.10

Why this is a domain service and not an aggregate method: the verdict composes the constitution's
threshold (Mandate), the payee's live status/digest (Mandate) and the ledger's headroom (Authority).
Pulling those three into `PaymentIntent` would make one immutable value know about two contexts.

Every input comes from the read that produced the verdict (A-6), and every refusal names a code from
the closed `DenialReason` set (A-5). The policy is pure: it reads no clock and no port.
"""

from __future__ import annotations

from datetime import datetime

from src.authority.domain.cap_ledger import CapLedger
from src.authority.domain.determination import Determination
from src.authority.domain.payment_intent import PaymentIntent
from src.authority.domain.ports import ConstitutionView, PayeeView
from src.authority.domain.services import DeterminationPolicy
from src.authority.domain.values import DenialReason
from src.mandate.domain.values import PayeeStatus

__all__ = ["StatutoryDeterminationPolicy"]

#: Every rule that can refuse a payment, in the order a human reads them: is the destination still
#: the one Mandate verified, is the payee still payable, is the bill new, is there money left.
_REFUSAL_ORDER = (
    DenialReason.PAYEE_FROZEN,
    DenialReason.PAYEE_QUARANTINED,
    DenialReason.DIGEST_MISMATCH,
    DenialReason.DUPLICATE_INVOICE,
    DenialReason.CAP_EXCEEDED,
)


class StatutoryDeterminationPolicy(DeterminationPolicy):
    """Compose the rules into one verdict, naming every rule that fired.

    Deliberate choices:

    * **All refusal codes are collected, not just the first.** A frozen payee whose digest also
      mismatches should say both — the console copy and the evidence envelope are more useful with the
      full picture, and A-5 asks for "at least one", not "exactly one".
    * **Cap headroom is a refusal code, not an exception here.** The decision is recorded (with the
      ledger snapshot) so the refusal is explainable. The *reservation* still refuses atomically if a
      concurrent hold lands between this read and the update (A-9).
    * **Escalation is decided only when nothing refuses.** A new payee above the cap is denied, not
      escalated: no signature can create headroom.
    """

    def decide(
        self,
        *,
        intent: PaymentIntent,
        constitution: ConstitutionView,
        payee: PayeeView,
        ledger: CapLedger,
        read_at: datetime,
        duplicate_invoice: bool = False,
    ) -> Determination:
        snapshot = ledger.committed + ledger.reserved
        fired: set[DenialReason] = set()

        if payee.status is PayeeStatus.FROZEN:
            fired.add(DenialReason.PAYEE_FROZEN)
        elif payee.status is PayeeStatus.QUARANTINED:
            fired.add(DenialReason.PAYEE_QUARANTINED)

        # A-2/A-13: the intent carries Mandate's digest. A record that no longer matches it means the
        # verified bank details changed after the read — refuse rather than pay the wrong account.
        if payee.digest != intent.bank_digest:
            fired.add(DenialReason.DIGEST_MISMATCH)

        if duplicate_invoice:
            fired.add(DenialReason.DUPLICATE_INVOICE)

        if ledger.headroom < intent.amount:
            fired.add(DenialReason.CAP_EXCEEDED)

        if fired:
            reasons = [code for code in _REFUSAL_ORDER if code in fired]
            return Determination.deny(
                intent_id=intent.id,
                reasons=reasons,
                constitution_version=constitution.version,
                payee_status_read=payee.status,
                read_at=read_at,
                ledger_snapshot=snapshot,
            )

        if intent.requires_owner_signature:
            return Determination.escalate(
                intent_id=intent.id,
                constitution_version=constitution.version,
                payee_status_read=payee.status,
                read_at=read_at,
                ledger_snapshot=snapshot,
            )

        return Determination.allow(
            intent_id=intent.id,
            constitution_version=constitution.version,
            payee_status_read=payee.status,
            read_at=read_at,
            ledger_snapshot=snapshot,
        )
