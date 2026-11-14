"""Wire schemas for the Mandate endpoints — the DTOs' transport shape.

Canonical: docs/architecture/modules/mandate.md#api-endpoints
Reference: docs/architecture/decisions/ADR-004-api-design.md

Amounts are integer micro-USDC and digests are hex, matching the DTOs (ADR-002). Routing details are
accepted on the two endpoints that hash them and never returned by any endpoint.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = [
    "CreateHouseholdRequest",
    "EligibilityResponse",
    "HouseholdResponse",
    "PayeeResponse",
    "PresentedDigestRequest",
    "PublishVersionRequest",
    "ReapproveRequest",
    "RegisterPayeeRequest",
    "RevealDigestResponse",
    "VersionResponse",
]


class CreateHouseholdRequest(BaseModel):
    owner_address: str = Field(description="0x-prefixed owner address; the only valid signer")
    owner_name: str
    payer_name: str
    agent_key_id: str = Field(description="Identifier of the agent's API key, never the key itself")
    cap_micro_usdc: int = Field(gt=0, description="Daily cap in USDC micro-units")
    threshold_micro_usdc: int = Field(ge=0, description="Auto-pay limit in USDC micro-units")
    require_signature_for_new_payee: bool = True
    owner_proof: str = Field(default="", description="EIP-712 signature over the mandate")


class HouseholdResponse(BaseModel):
    household_id: str
    constitution_id: str
    owner_id: str
    payer_id: str
    agent_id: str
    version: int
    events: tuple[str, ...] = ()


class PublishVersionRequest(BaseModel):
    cap_micro_usdc: int = Field(gt=0)
    threshold_micro_usdc: int = Field(ge=0)
    require_signature_for_new_payee: bool = True
    owner_proof: str = ""


class VersionResponse(BaseModel):
    constitution_id: str
    version: int
    cap_micro_usdc: int
    threshold_micro_usdc: int
    require_signature_for_new_payee: bool
    content_hash: str
    status: str
    events: tuple[str, ...] = ()


class RegisterPayeeRequest(BaseModel):
    name: str
    address: str
    routing_scheme: str = ""
    routing_account_number: str = Field(default="", description="Hashed on arrival; never stored")
    routing_number: str = ""
    owner_proof: str = ""


class ReapproveRequest(BaseModel):
    routing_scheme: str = ""
    routing_account_number: str = ""
    routing_number: str = ""
    owner_proof: str = ""


class PresentedDigestRequest(BaseModel):
    presented_digest: str = Field(description="Digest of the routing details on the invoice")
    invoice_id: str = ""


class PayeeResponse(BaseModel):
    payee_id: str
    name: str
    address: str
    verified_digest: str
    status: str
    events: tuple[str, ...] = ()
    quarantined: bool = False


class RevealDigestResponse(BaseModel):
    digest: str


class EligibilityResponse(BaseModel):
    verdict: str
    reason: str | None = None
