"""Wire shapes for the eight console endpoints (OpenAPI is the React team's contract).

Canonical: docs/architecture/decisions/ADR-004-api-design.md
Reference: docs/architecture/modules/console.md#api-endpoints

The response models are a second whitelist, not a formatting layer: a field that is not declared
here cannot reach a client even if a projection accidentally gained it (CON-01). Each model is built
from its frozen DTO by a classmethod, so the mapping is explicit and greppable.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.console.application.dto import (
    ApprovalInboxItem,
    ConstitutionReadModel,
    EvidenceReadModel,
    PayeeReadModel,
    PaymentReadModel,
    SignatureOutcome,
    VerificationReadModel,
)

__all__ = [
    "ApprovalInboxItemResponse",
    "ConstitutionResponse",
    "EvidenceResponse",
    "PayeeResponse",
    "PayerBillResponse",
    "SignatureOutcomeResponse",
    "VerificationResponse",
]


class ApprovalInboxItemResponse(BaseModel):
    approval_id: str
    intent_id: str
    invoice_id: str
    payee_name: str
    payee_address: str = Field(description="Byte-identical to Authority's intent (CON-02)")
    amount_usdc: str = Field(description="Exact decimal string — never re-rendered (CON-02)")
    bank_digest: str = Field(description="Byte-identical to Authority's intent (CON-02)")
    is_new_payee: bool
    requires_owner_signature: bool
    reason_codes: list[str]
    expires_at: datetime
    typed_data_hash: str

    @classmethod
    def from_dto(cls, item: ApprovalInboxItem) -> ApprovalInboxItemResponse:
        return cls(
            approval_id=item.approval_id,
            intent_id=item.intent_id,
            invoice_id=item.invoice_id,
            payee_name=item.payee_name,
            payee_address=item.payee_address,
            amount_usdc=item.amount_usdc,
            bank_digest=item.bank_digest,
            is_new_payee=item.is_new_payee,
            requires_owner_signature=item.requires_owner_signature,
            reason_codes=list(item.reason_codes),
            expires_at=item.expires_at,
            typed_data_hash=item.typed_data_hash,
        )


class SignatureOutcomeResponse(BaseModel):
    granted: bool
    reason_plain: str | None = None
    reason_codes: list[str]

    @classmethod
    def from_dto(cls, outcome: SignatureOutcome) -> SignatureOutcomeResponse:
        return cls(
            granted=outcome.granted,
            reason_plain=outcome.reason_plain,
            reason_codes=[str(code) for code in outcome.reason_codes],
        )


class PayerBillResponse(BaseModel):
    invoice_id: str
    payee_name: str
    amount_usdc: str
    status: str
    status_plain: str
    settled_at: datetime | None
    tx_hash: str | None
    payout_simulated: bool
    payout_label: str | None
    refusal_reason: str | None

    @classmethod
    def from_dto(cls, bill: PaymentReadModel) -> PayerBillResponse:
        return cls(
            invoice_id=bill.invoice_id,
            payee_name=bill.payee_name,
            amount_usdc=bill.amount_usdc,
            status=str(bill.status),
            status_plain=bill.status_plain,
            settled_at=bill.settled_at,
            tx_hash=bill.tx_hash,
            payout_simulated=bill.payout_simulated,
            payout_label=bill.payout_label,
            refusal_reason=bill.refusal_reason,
        )


class PayeeResponse(BaseModel):
    payee_id: str
    display_name: str
    status: str
    status_plain: str

    @classmethod
    def from_dto(cls, payee: PayeeReadModel) -> PayeeResponse:
        return cls(
            payee_id=payee.payee_id,
            display_name=payee.display_name,
            status=payee.status,
            status_plain=payee.status_plain,
        )


class ConstitutionResponse(BaseModel):
    version: str
    cap_usdc: str
    threshold_usdc: str
    published_at: datetime

    @classmethod
    def from_dto(cls, constitution: ConstitutionReadModel) -> ConstitutionResponse:
        return cls(
            version=constitution.version,
            cap_usdc=constitution.cap_usdc,
            threshold_usdc=constitution.threshold_usdc,
            published_at=constitution.published_at,
        )


class EvidenceResponse(BaseModel):
    envelope_id: str
    event_type: str
    occurred_at: datetime
    result: str
    anchor_tx: str | None

    @classmethod
    def from_dto(cls, evidence: EvidenceReadModel) -> EvidenceResponse:
        return cls(
            envelope_id=evidence.envelope_id,
            event_type=evidence.event_type,
            occurred_at=evidence.occurred_at,
            result=evidence.result,
            anchor_tx=evidence.anchor_tx,
        )


class VerificationResponse(BaseModel):
    envelope_id: str
    outcome: str
    checked_at: datetime
    detail: str = ""

    @classmethod
    def from_dto(cls, verification: VerificationReadModel) -> VerificationResponse:
        return cls(
            envelope_id=verification.envelope_id,
            outcome=str(verification.outcome),
            checked_at=verification.checked_at,
            detail=verification.detail,
        )
