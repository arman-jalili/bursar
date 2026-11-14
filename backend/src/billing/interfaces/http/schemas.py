"""Request/response schemas for the Billing HTTP contract (concrete).

Canonical: docs/architecture/modules/billing.md#api-endpoints
Reference: docs/contracts/billing-contract-freeze.md §2.10

These are Pydantic models, not the application DTOs. Keeping them separate matters for B-5: the wire
model declares **exactly** the fields the endpoint accepts. `ProposePaymentRequest` allows extras only
so the router can see and reject them by name with `422 PROPOSAL_REJECTED` — a model that dropped them
would sanitize the proposal, which is the failure mode B-5 names.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AttemptResponse",
    "InvoiceListResponse",
    "InvoiceResponse",
    "ProposePaymentRequest",
    "RecordInvoiceRequest",
    "RecordInvoiceResponse",
]


class RecordInvoiceRequest(BaseModel):
    """`POST /v1/invoices` — the bill document plus Mandate's payee reference."""

    model_config = ConfigDict(extra="forbid")

    payee_id: str
    amount_micro_usdc: int = Field(gt=0)
    due_date: date
    document: dict[str, object]
    presented_digest: str


class InvoiceResponse(BaseModel):
    invoice_id: str
    payee_id: str
    invoice_hash: str
    amount_micro_usdc: int
    due_date_iso: str
    presented_digest: str
    status: str


class RecordInvoiceResponse(BaseModel):
    invoice: InvoiceResponse
    duplicate: bool = False
    events: list[str] = Field(default_factory=list)


class InvoiceListResponse(BaseModel):
    items: list[InvoiceResponse]
    events: list[str] = Field(default_factory=list)


class ProposePaymentRequest(BaseModel):
    """`POST /v1/attempts` — an invoice id and an optional claimed amount, and nothing else.

    `extra="allow"` is deliberate: the router must *see* a smuggled `payee_address` to reject it with
    `PROPOSAL_REJECTED`. Dropping unknown fields here would turn rejection into sanitization (B-5).
    """

    model_config = ConfigDict(extra="allow")

    invoice_id: str
    proposed_amount_micro_usdc: int | None = None


class AttemptResponse(BaseModel):
    attempt_id: str
    invoice_id: str
    status: str
    events: list[str] = Field(default_factory=list)
