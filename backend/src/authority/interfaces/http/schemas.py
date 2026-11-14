"""Wire schemas for the Authority endpoints — the frozen shapes from the contract.

Canonical: .pi/architecture/modules/authority.md#api-endpoints
Reference: docs/contracts/authority-contract-freeze.md §2.9

Two deliberate constraints:

* **`extra="forbid"` on every request.** `POST /v1/precondition/check` must reject `payee_address` and
  `bank_digest` with a 422 rather than quietly ignoring them (A-2): an API that accepts routing data and
  discards it teaches a caller that routing data is accepted.
* **Amounts are integer micro-USDC** (ADR-002) and are echoed only where the caller sent them or where
  the ledger row is public to the owner. No endpoint returns raw routing details.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ApprovalResponse",
    "DeterminationResponse",
    "IntentResponse",
    "LedgerResponse",
    "PreconditionCheckRequest",
    "PreconditionCheckResponse",
    "SettlementOutcomeRequest",
    "SettlementOutcomeResponse",
    "SignatureRequest",
    "SignatureResponse",
]


class _StrictRequest(BaseModel):
    """Reject unknown fields — routing data must not be silently tolerated (A-2)."""

    model_config = ConfigDict(extra="forbid")


class PreconditionCheckRequest(_StrictRequest):
    intent_id: str = Field(description="The enforcement client's correlation id")
    invoice_id: str
    payee_id: str
    amount_micro_usdc: int = Field(ge=0, description="The invoice amount, in USDC micro-units")


class PreconditionCheckResponse(BaseModel):
    decision: Literal["allow", "deny", "escalate"]
    reason_codes: tuple[str, ...] = ()
    determination_id: str


class DeterminationResponse(BaseModel):
    determination_id: str
    intent_id: str
    verdict: Literal["allow", "deny", "escalate"]
    reason_codes: tuple[str, ...] = ()
    constitution_version: int
    payee_status: str
    read_at: datetime | None = None


class IntentResponse(BaseModel):
    intent_id: str
    invoice_id: str
    payee_id: str
    payee_address: str
    amount_micro_usdc: int
    bank_digest: str
    is_new_payee: bool
    requires_owner_signature: bool
    constitution_version: int


class LedgerResponse(BaseModel):
    day: str
    cap_micro_usdc: int
    committed_micro_usdc: int
    reserved_micro_usdc: int
    headroom_micro_usdc: int


class ApprovalResponse(BaseModel):
    approval_id: str
    intent_id: str
    typed_data_hash: str
    expires_at: datetime
    status: str


class SignatureRequest(_StrictRequest):
    signature_hex: str = Field(description="65-byte r||s||v signature over the intent's typed data")


class SignatureResponse(BaseModel):
    granted: bool
    approval_id: str
    events: tuple[str, ...] = ()


class SettlementOutcomeRequest(_StrictRequest):
    outcome: Literal["confirmed", "reverted"]
    tx_hash: str = ""


class SettlementOutcomeResponse(BaseModel):
    reservation_id: str
    day: str
    cap_micro_usdc: int
    committed_micro_usdc: int
    reserved_micro_usdc: int
    headroom_micro_usdc: int
    events: tuple[str, ...] = ()
