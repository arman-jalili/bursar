"""PaymentIntent — the unit of authority, immutable once issued (frozen).

Canonical: docs/architecture/modules/authority.md#aggregate-paymentintent
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

import asyncio
import concurrent.futures
import hashlib
import inspect
import json
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any, overload

from src.authority.domain.errors import AmountMismatch, AuthorityRefusal
from src.authority.domain.ids import IntentId, new_id
from src.authority.domain.ports import (
    AttemptView,
    ConstitutionView,
    InvoiceView,
    MandateView,
    PayeeView,
)
from src.authority.domain.values import Money
from src.mandate.domain.values import BankDigest, PayeeAddress, PayeeStatus
from src.shared.domain.errors import ErrorCode

__all__ = ["PaymentIntent"]


@overload
def _resolve[T](value: Coroutine[Any, Any, T]) -> T: ...


@overload
def _resolve[T](value: T) -> T: ...


def _resolve(value: Any) -> Any:
    """Read a port answer from a synchronous factory.

    `MandateView` is asynchronous because the real adapter is an HTTP call, while `issue` is a
    synchronous factory (a domain aggregate must not require an event loop to be constructed).
    A caller inside an event loop should pre-read the views and use `from_reads`; this helper is
    for the synchronous path and for the contract tests, which pass an async stub directly.
    """
    if not inspect.isawaitable(value):
        return value

    async def _await(awaitable: Any) -> Any:
        return await awaitable

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_await(value))
    # Inside a loop: run the read on a private loop so the synchronous contract still holds.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _await(value)).result()


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
        cls,
        attempt: AttemptView,
        mandate: MandateView,
        invoice: InvoiceView,
        *,
        household_id: str = "",
    ) -> PaymentIntent:
        """Build the intent from **Mandate-owned** data plus identifiers from the attempt.

        Everything the proposal carries beyond ids is discarded: the address and digest are read from
        `mandate`, the amount from the invoice (A-2, A-3), and the signature requirement is derived
        (A-4).

        Raises:
            AmountMismatch: the attempt amount differs from the invoice amount (A-3).
            AuthorityRefusal: Mandate reports the payee ineligible (A-2, A-6).
        """
        if attempt.claimed_amount is not None and attempt.claimed_amount != invoice.amount:
            raise AmountMismatch(
                str(attempt.claimed_amount.micro_usdc), str(invoice.amount.micro_usdc)
            )

        payee: PayeeView
        constitution: ConstitutionView
        try:
            payee = _resolve(mandate.payee(invoice.payee_id))
            constitution = _resolve(mandate.constitution_in_force(household_id))
        except (ConnectionError, TimeoutError, OSError) as exc:
            # AC 11 / ADR-007: an unreadable Mandate is a "no", not a "probably".
            refusal = AuthorityRefusal(
                ErrorCode.INTERNAL,
                "Mandate could not be read; failing closed.",
                retryable=True,
            )
            refusal.reason_code = "upstream_unavailable"
            raise refusal from exc

        # A-6: the decision uses the payee record read *now*. A frozen or quarantined payee cannot
        # produce an intent, so scenario 3 (frozen after planning) fails at the consequence, not later.
        if payee.status is PayeeStatus.FROZEN:
            refusal = AuthorityRefusal(
                ErrorCode.PAYEE_FROZEN, "The payee is frozen; no intent may be issued."
            )
            refusal.reason_code = "payee_frozen"
            raise refusal
        if payee.status is PayeeStatus.QUARANTINED:
            refusal = AuthorityRefusal(
                ErrorCode.PAYEE_QUARANTINED, "The payee is quarantined; no intent may be issued."
            )
            refusal.reason_code = "payee_quarantined"
            raise refusal

        is_new_payee = payee.status is PayeeStatus.NEW
        # A-4: derived, never passed in. Strict `>` so paying exactly the threshold auto-pays.
        requires_signature = (
            is_new_payee and constitution.require_signature_for_new_payee
        ) or invoice.amount > constitution.threshold

        return cls(
            id=IntentId(new_id()),
            invoice_id=invoice.invoice_id,
            payee_id=payee.payee_id,
            payee_address=payee.address,
            amount=invoice.amount,
            bank_digest=payee.digest,
            is_new_payee=is_new_payee,
            requires_owner_signature=requires_signature,
            constitution_version=constitution.version,
        )

    @classmethod
    def from_reads(
        cls,
        *,
        invoice_id: str,
        payee: PayeeView,
        constitution_version: int,
        require_signature_for_new_payee: bool,
        threshold: Money,
        amount: Money,
    ) -> PaymentIntent:
        """Pure construction path for async callers that have already re-read Mandate (A-6).

        No port is touched here: the application layer performs the read inside its unit of work and
        passes the views. Validation of amount equality and payee eligibility happened at the read.
        """
        is_new_payee = payee.status is PayeeStatus.NEW
        return cls(
            id=IntentId(new_id()),
            invoice_id=invoice_id,
            payee_id=payee.payee_id,
            payee_address=payee.address,
            amount=amount,
            bank_digest=payee.digest,
            is_new_payee=is_new_payee,
            requires_owner_signature=(is_new_payee and require_signature_for_new_payee)
            or amount > threshold,
            constitution_version=constitution_version,
        )

    def signed_payload(self) -> dict[str, Any]:
        """The EIP-712 message: the exact fields the owner signs and the contract re-derives."""
        return {
            "intentId": self.id,
            "invoiceId": self.invoice_id,
            "payee": self.payee_id,
            "payeeAddress": self.payee_address.value,
            "amountUsdc": self.amount.micro_usdc,
            "bankDigest": self.bank_digest.hash,
            "isNewPayee": self.is_new_payee,
            "requiresOwnerSignature": self.requires_owner_signature,
            "constitutionVersion": self.constitution_version,
        }

    def typed_data_hash(self) -> str:
        """Canonical hash of `signed_payload()` — the one binding every approval compares (A-13)."""
        canonical = json.dumps(self.signed_payload(), sort_keys=True, separators=(",", ":"))
        return "0x" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
