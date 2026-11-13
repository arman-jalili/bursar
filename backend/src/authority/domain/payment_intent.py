"""PaymentIntent — the unit of authority, immutable once issued (frozen).

Canonical: .pi/architecture/modules/authority.md#aggregate-paymentintent
Reference: docs/contracts/authority-contract-freeze.md (A-1 … A-4)

    A-1  immutable after issue — no setter, no `dict.update` merge
    A-2  `payee_address` and `bank_digest` come from Mandate's verified record, never from the
         invoice or the proposal
    A-3  `amount` must equal the invoice amount; an agent-supplied amount is not accepted
    A-4  `requires_owner_signature` is derived (new payee OR amount > threshold), never passed in

A-2 is the anti-injection rule: the intent's routing fields are read from `MandateView`, so a proposal
that carries its own `payee_address` has nowhere to put it. A-4 is the anti-self-waiver rule: if
`requires_owner_signature` were an argument, the caller could simply pass `False`.

`signed_payload()` exists because the exact bytes matter twice — once for the Python verifier and once
for `PaymentRouter`. One definition, two consumers (Phase B generates both from it).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.authority.domain.ids import IntentId
from src.authority.domain.ports import AttemptView, InvoiceView, MandateView
from src.authority.domain.values import Money
from src.mandate.domain.values import BankDigest, PayeeAddress

__all__ = ["PaymentIntent"]


@dataclass(frozen=True, slots=True)
class PaymentIntent:
    """The canonical, code-constructed description of one payment.

    Frozen dataclass on purpose: A-1 says the intent cannot change between authorization and signature,
    and an immutable type is the only version of that promise the compiler can keep.
    """

    id: IntentId
    invoice_id: str
    payee_id: str
    payee_address: PayeeAddress
    amount: Money
    bank_digest: BankDigest
    is_new_payee: bool
    requires_owner_signature: bool
    constitution_version: int

    @classmethod
    def issue(
        cls, attempt: AttemptView, mandate: MandateView, invoice: InvoiceView
    ) -> PaymentIntent:
        """Build the intent from **Mandate-owned** data plus identifiers from the attempt.

        Everything the proposal carries beyond ids is discarded: the address and digest are read from
        `mandate`, the amount from the invoice (A-2, A-3), and the signature requirement is derived
        (A-4).

        Raises:
            AuthorityRefusal: the attempt amount differs from the invoice amount (A-3).
        """
        raise NotImplementedError("A-2 — see module doc")

    def signed_payload(self) -> dict[str, Any]:
        """The EIP-712 message: the exact fields the owner signs and the contract re-derives."""
        raise NotImplementedError("A-1 — see module doc")
