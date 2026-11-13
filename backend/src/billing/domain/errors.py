"""Billing refusal vocabulary (frozen).

Canonical: .pi/architecture/modules/billing.md#components
Reference: docs/contracts/billing-contract-freeze.md §2.5

Every refusal here extends the shared `RefusalError`, so:

* the API layer needs **no Billing-specific exception handling** — a refusal is a documented `409` with a
  domain code everywhere in this context (ADR-004);
* a test can assert `pytest.raises(RefusalError)` and still be specific about the cause.

Each class exists because one invariant needs it named:

    DuplicateInvoice       B-3  the same bill arrived twice (replay)
    InvoiceNotPayable      B-1  an attempt is already in flight
    InvoiceAlreadySettled  B-2  the bill is closed
    ProposalRejected       B-5  the proposal carried a forbidden field
    AmountMismatch         B-6  the proposal edited the amount

Payloads are passed as an explicit `details` mapping, never as a `**kwargs` tail: a splat can smuggle a key
named `retryable` or `code` into `RefusalError` and silently rewrite the refusal's semantics.
"""

from __future__ import annotations

from src.shared.domain.errors import ErrorCode, RefusalError

__all__ = [
    "AmountMismatch",
    "BillingRefusal",
    "DuplicateInvoice",
    "InvoiceAlreadySettled",
    "InvoiceNotPayable",
    "ProposalRejected",
]


class BillingRefusal(RefusalError):
    """Base for every refusal this context raises. Maps to HTTP 409 via the shared handler."""

    reason_code: str = "billing_refused"


class DuplicateInvoice(BillingRefusal):
    """A second invoice with the same hash is the same bill (B-3)."""

    def __init__(self, invoice_hash: str = "", **extra: str) -> None:
        super().__init__(
            ErrorCode.DUPLICATE_INVOICE,
            "This invoice was already recorded; it is the same bill.",
            details={"invoice_hash": invoice_hash, **extra},
        )
        self.reason_code = ErrorCode.DUPLICATE_INVOICE.value


class InvoiceNotPayable(BillingRefusal):
    """The invoice already has a non-terminal attempt (B-1)."""

    def __init__(self, invoice_id: str = "", status: str = "", **extra: str) -> None:
        super().__init__(
            ErrorCode.CONFLICT,
            "This invoice already has a payment in progress.",
            details={"invoice_id": invoice_id, "status": status, **extra},
        )
        self.reason_code = "invoice_not_payable"


class InvoiceAlreadySettled(InvoiceNotPayable):
    """The invoice is closed; a settlement is final (B-2)."""

    def __init__(self, invoice_id: str = "", **extra: str) -> None:
        super().__init__(invoice_id=invoice_id, status="settled", **extra)
        self.message = "This invoice is already settled."
        self.reason_code = "invoice_already_settled"


class ProposalRejected(BillingRefusal):
    """The proposal supplied a forbidden field and was rejected outright (B-5).

    Rejected, not sanitized: silently dropping the field would teach the caller which fields survive, and
    the next attempt would omit only the ones that are checked.
    """

    def __init__(self, offending_fields: tuple[str, ...] = (), **extra: str) -> None:
        super().__init__(
            ErrorCode.PROPOSAL_REJECTED,
            "The proposal carried fields this endpoint does not accept.",
            details={
                "offending_fields": ",".join(sorted(offending_fields)) or "unknown",
                **extra,
            },
        )
        self.reason_code = ErrorCode.PROPOSAL_REJECTED.value


class AmountMismatch(BillingRefusal):
    """The proposal amount differs from the invoice amount (B-6)."""

    def __init__(self, proposed: str = "", invoiced: str = "", **extra: str) -> None:
        super().__init__(
            ErrorCode.AMOUNT_MISMATCH,
            "The proposed amount does not match the invoice.",
            details={
                "proposed_micro_usdc": proposed,
                "invoiced_micro_usdc": invoiced,
                **extra,
            },
        )
        self.reason_code = ErrorCode.AMOUNT_MISMATCH.value
