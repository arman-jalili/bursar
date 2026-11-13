"""Authority domain — framework-free and persistence-ignorant.

Canonical: .pi/architecture/modules/authority.md#components
Reference: docs/contracts/authority-contract-freeze.md

    values.py          Money (re-exported from the shared kernel) · DeterminationVerdict · DenialReason
    ids.py             IntentId · DeterminationId · ReservationId · ApprovalId
    errors.py          AuthorityRefusal · CapExceeded · ApprovalInvalid · …
    payment_intent.py  PaymentIntent            (A-1 … A-4)
    determination.py   Determination             (A-5 … A-8)
    cap_ledger.py      CapLedger · Reservation   (A-9 … A-12)
    approval.py        Approval · OwnerSignature (A-13 … A-15)
    services.py        DeterminationPolicy · ApprovalBinder (stateless domain services)
    events.py          the twelve frozen event payload schemas
    repositories.py    the four ports
    ports.py           MandateView · AttemptViewPort (ACL to upstream contexts)

`Money` is **not** redefined here: the shared kernel already has it, and two money types would
eventually disagree about rounding. Authority re-exports the one definition so this context's contract
still names it.
"""

from src.shared.domain.money import Money

__all__ = ["Money"]
