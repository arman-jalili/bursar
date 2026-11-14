"""Request/response schemas for the Evidence HTTP contract (concrete).

Canonical: .pi/architecture/modules/evidence.md#api-endpoints
Reference: docs/contracts/evidence-contract-freeze.md §2.9

The wire model is separate from the application DTO so the endpoint declares exactly what it returns.
`payload` is present only for `?full=1`: a list view that leaked every fact body would make the
"summary vs full" distinction meaningless. The failure body is the shared ADR-004 envelope, so there
is no Evidence-specific error schema here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

__all__ = [
    "AnchorResponse",
    "EnvelopeListResponse",
    "EnvelopeResponse",
    "VerifyResponse",
]


class EnvelopeResponse(BaseModel):
    envelope_id: str
    event_type: str
    subject_intent_id: str | None = None
    subject_invoice_id: str | None = None
    subject_payee_id: str | None = None
    constitution_version: str | None = None
    actor: str
    occurred_at: datetime
    hmac: str
    previous_hash: str | None = None
    anchor_mode: str
    envelope_hash: str
    anchor_tx: str | None = None
    #: Only populated for `?full=1`.
    payload: dict[str, Any] | None = None


class EnvelopeListResponse(BaseModel):
    items: list[EnvelopeResponse]
    next_cursor: str | None = None


class VerifyResponse(BaseModel):
    """`200` with `VERIFIED`/`UNANCHORED`; a mismatch is a `409` shared envelope."""

    result: str
    field: str | None = None
    anchor_tx: str | None = None


class AnchorResponse(BaseModel):
    anchor_tx: str
    block_number: int
    chain_id: int
