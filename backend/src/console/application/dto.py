"""Console read models (frozen) — DTOs, not entities.

Canonical: .pi/architecture/modules/console.md#entity-relationship--projections-only-no-aggregates
Reference: docs/contracts/console-contract-freeze.md §2.1

Two decisions encoded in the types rather than in a formatter:

* `amount_usdc` is the **exact decimal string** Authority produced. A float round-trip turns
  `320.00` into `319.99999999999994`; a `Decimal` renderer is a formatting decision the console is
  not allowed to make (CON-02).
* `payee_address` and `bank_digest` are copied byte-for-byte — mixed-case address checksums are part
  of the value, not decoration (CON-02).

`PaymentReadModel.tx_hash` is supplied by Settlement but must not be rendered on the payer surface;
vocabulary is enforced on copy (CON-05), not by hiding the field and re-fetching it elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from src.console.application.refusals import DenialReasonCode

__all__ = [
    "ApprovalInboxItem",
    "BillStatus",
    "ConstitutionReadModel",
    "EvidenceReadModel",
    "PayeeReadModel",
    "PaymentReadModel",
    "SignatureOutcome",
    "SignatureSubmission",
    "Surface",
    "VerificationOutcome",
    "VerificationReadModel",
]


class Surface(StrEnum):
    """The six screens that may receive upstream data — one whitelist each (CON-01)."""

    OWNER_INBOX = "owner_inbox"
    PAYER_BILL = "payer_bill"
    PAYEE_LIST = "payee_list"
    CONSTITUTION = "constitution"
    EVIDENCE = "evidence"
    VERIFICATION = "verification"


class BillStatus(StrEnum):
    """Closed set; the payer copy table must cover all four members (CON-05)."""

    RECEIVED = "RECEIVED"
    IN_FLIGHT = "IN_FLIGHT"
    SETTLED = "SETTLED"
    REFUSED = "REFUSED"


class VerificationOutcome(StrEnum):
    """Evidence's verdict, proxied. `UNKNOWN` is explicit — never inferred from a falsy value."""

    VERIFIED = "verified"
    TAMPERED = "tampered"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ApprovalInboxItem:
    """One pending signature request as the owner sees it (FR-024)."""

    approval_id: str
    intent_id: str
    invoice_id: str
    payee_name: str
    #: Byte-identical to Authority's intent — no truncation, no re-checksumming (CON-02).
    payee_address: str
    #: Exact decimal string, never re-rendered (CON-02).
    amount_usdc: str
    #: Byte-identical to Authority's intent (CON-02).
    bank_digest: str
    is_new_payee: bool
    requires_owner_signature: bool
    reason_codes: tuple[str, ...]
    expires_at: datetime
    #: Binds the signature to the displayed fields; owner surface only (CON-01).
    typed_data_hash: str


@dataclass(frozen=True, slots=True)
class PaymentReadModel:
    """One bill in household language (FR-025)."""

    invoice_id: str
    payee_name: str
    amount_usdc: str
    status: BillStatus
    #: Household-language status; derived from `status`, never from a raw upstream string (CON-05).
    status_plain: str
    settled_at: datetime | None
    tx_hash: str | None
    #: True for every demo settlement (CON-06).
    payout_simulated: bool
    #: The demo label that travels with the bill; None when no settlement backs it (CON-06).
    payout_label: str | None
    #: Household reason derived from the closed code set; never the raw code (CON-07).
    refusal_reason: str | None


@dataclass(frozen=True, slots=True)
class EvidenceReadModel:
    envelope_id: str
    event_type: str
    occurred_at: datetime
    result: str
    anchor_tx: str | None


@dataclass(frozen=True, slots=True)
class VerificationReadModel:
    envelope_id: str
    outcome: VerificationOutcome
    checked_at: datetime
    detail: str = ""


@dataclass(frozen=True, slots=True)
class PayeeReadModel:
    payee_id: str
    display_name: str
    status: str
    status_plain: str


@dataclass(frozen=True, slots=True)
class ConstitutionReadModel:
    version: str
    cap_usdc: str
    threshold_usdc: str
    published_at: datetime


@dataclass(frozen=True, slots=True)
class SignatureSubmission:
    """The owner signature as received — bytes, because the console must not re-encode it (CON-03)."""

    approval_id: str
    raw_body: bytes
    content_type: str
    owner_scope: str


@dataclass(frozen=True, slots=True)
class SignatureOutcome:
    granted: bool
    #: Household-language refusal, derived from `reason_codes` (CON-07).
    reason_plain: str | None
    reason_codes: tuple[DenialReasonCode, ...]
