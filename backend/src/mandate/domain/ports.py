"""Domain ports — the narrow interfaces the aggregates depend on.

Canonical: docs/architecture/modules/mandate.md#components
Reference: docs/architecture/decisions/ADR-005-authentication-authorization.md

Two ports, and both exist to keep a decision out of the aggregate:

`OwnerSignatureProof` — the aggregate must be able to say "this change is owner-authorized"
(FR-015's principle applied inside Mandate) without knowing how a signature is verified. EIP-712
verification is an adapter concern; the domain only needs the question answered. Passing proof as an
*argument* also makes "who authorized this" un-forgeable: there is no flag to set.

`EligibilityResolver` — combines the constitution flag (`require_signature_for_new_payee`) with the
payee status. It spans two aggregates, so it belongs to neither and lives here as a domain service
contract.

Frozen contract v1: these are Protocols/ABCs, not implementations. The concrete verifier arrives
with the proofing item; the resolver with the domain-services item.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

__all__ = ["EligibilityResolver", "OwnerSignatureProof"]

from src.mandate.domain.values import Eligibility, PayeeStatus


@runtime_checkable
class OwnerSignatureProof(Protocol):
    """Proof that the owner authorized one specific change.

    `signs(*subjects)` is deliberately variadic: H-5 signs (household, cap, threshold), P-1 signs
    (digest, address), P-5 signs (payee_id, new_digest). A verifier decides what the signed payload
    was; the aggregate only asks whether *this* change is covered.
    """

    def signs(self, *subjects: object) -> bool:
        """True when the signed payload covers exactly these subjects."""
        ...


class EligibilityResolver(ABC):
    """Derives the payability verdict from payee status and constitution flags (FR-012).

    Extracted as a domain service because it is the one rule that needs both aggregates at once:
    `PayeeStatus.NEW` escalates only when the in-force version requires a signature for new payees.
    """

    @abstractmethod
    def resolve(
        self, status: PayeeStatus, *, require_signature_for_new_payee: bool = True
    ) -> Eligibility:
        """Map a payee status to allow / escalate / deny with a reason code."""
        raise NotImplementedError("EligibilityResolver.resolve — see module doc AC #11")
