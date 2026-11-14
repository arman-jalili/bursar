"""PaymentAttempt — the agent's only legal output (frozen).

Canonical: docs/architecture/modules/billing.md#components-paymentattempt
Reference: docs/contracts/billing-contract-freeze.md (B-5, B-1, B-2, B-6, B-7)

    B-5  a proposal supplying a command path, payee address, cap or threshold is rejected outright
    B-1  at most one non-terminal attempt per invoice
    B-2  a settled invoice accepts no attempts
    B-6  the amount must equal the invoice amount
    B-7  only an allow/escalate determination dispatches; a refusal is terminal and side-effect free

`from_proposal` is the **only** entry point and it *is* the anti-corruption boundary: the payload may
carry identifiers, and anything else is rejected by name. Rejecting rather than sanitizing matters —
a sanitized proposal teaches the caller which fields survive the filter.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from src.billing.domain.errors import (
    AmountMismatch,
    BillingRefusal,
    InvoiceAlreadySettled,
    InvoiceNotPayable,
    ProposalRejected,
)
from src.billing.domain.events import AttemptDispatched, AttemptRefused, PaymentProposed
from src.billing.domain.ids import AttemptId, InvoiceId, new_id
from src.billing.domain.invoice import Invoice
from src.billing.domain.values import AttemptStatus, InvoiceStatus
from src.shared.domain.aggregate import AggregateRoot
from src.shared.domain.errors import ErrorCode

__all__ = ["FORBIDDEN_PROPOSAL_KEYS", "PaymentAttempt"]

#: Keys a proposal must never carry. Not "ignored" — a proposal containing any of these is refused
#: (B-5), because a field the agent may not set is a field the agent should not be able to send.
FORBIDDEN_PROPOSAL_KEYS: frozenset[str] = frozenset(
    {
        "command",
        "command_path",
        "payee_address",
        "cap",
        "threshold",
        "constitution_version",
        "requires_owner_signature",
        "is_new_payee",
    }
)

#: The whole proposal vocabulary. Everything else is rejected, not dropped (B-5).
_ALLOWED_PROPOSAL_KEYS: frozenset[str] = frozenset({"invoice_id", "proposed_amount_micro_usdc"})

#: Determinations that may move an attempt toward dispatch (B-7). An allow-list, not a deny-list:
#: a new refusal code added by Authority must be refused here by default.
_DISPATCH_DETERMINATIONS: frozenset[str] = frozenset({"allow", "escalate"})

#: Statuses from which an attempt can no longer move forward (B-7).
_TERMINAL_ATTEMPT_STATUSES = frozenset(
    {AttemptStatus.SETTLED, AttemptStatus.REFUSED, AttemptStatus.EXPIRED}
)


@dataclass(eq=False)
class PaymentAttempt(AggregateRoot):
    """The agent's structured proposal to pay one invoice. Carries no authority of its own."""

    id: AttemptId
    invoice_id: InvoiceId
    status: AttemptStatus

    #: The in-memory invoice this attempt was proposed against, so a refusal can free it again (B-1).
    #: Rehydrated attempts leave this empty; the application service persists the invoice status.
    _invoice: Invoice | None = field(default=None, init=False, repr=False, compare=False)

    @classmethod
    def from_proposal(cls, payload: Mapping[str, object], invoice: Invoice) -> PaymentAttempt:
        """Translate an untrusted proposal into an attempt in status `PROPOSED`.

        Raises:
            ProposalRejected: the payload carried a forbidden key (B-5).
            InvoiceAlreadySettled: the invoice is closed (B-2).
            InvoiceNotPayable: an attempt is already in flight (B-1).
            AmountMismatch: the proposed amount differs from the invoice amount (B-6).
        """
        keys = {str(key) for key in payload}
        offending = keys & FORBIDDEN_PROPOSAL_KEYS
        if offending:
            raise ProposalRejected(tuple(sorted(offending)))

        unknown = keys - _ALLOWED_PROPOSAL_KEYS
        if unknown:
            raise ProposalRejected(tuple(sorted(unknown)))

        if invoice.status is InvoiceStatus.SETTLED:
            raise InvoiceAlreadySettled(str(invoice.id))
        if not invoice.can_accept_attempt():
            raise InvoiceNotPayable(str(invoice.id), invoice.status.value)

        proposed = payload.get("proposed_amount_micro_usdc")
        if proposed is not None and (
            isinstance(proposed, bool)
            or not isinstance(proposed, int)
            or proposed != invoice.amount.micro_usdc
        ):
            raise AmountMismatch(proposed=str(proposed), invoiced=str(invoice.amount.micro_usdc))

        attempt = cls(
            id=AttemptId(new_id()),
            invoice_id=invoice.id,
            status=AttemptStatus.PROPOSED,
        )
        attempt._invoice = invoice
        invoice.status = InvoiceStatus.IN_FLIGHT
        invoice._active_attempt = attempt
        attempt.record(
            PaymentProposed(
                attempt_id=str(attempt.id),
                invoice_id=str(invoice.id),
                payee_id=str(invoice.payee_id),
                amount_micro_usdc=invoice.amount.micro_usdc,
            )
        )
        return attempt

    def mark_dispatched(self, *, determination: str) -> None:
        """Move to `DISPATCHED` only for an allow/escalate determination (B-7).

        Raises:
            BillingRefusal: the determination is a refusal — the attempt must stay terminal, with no
                side effect. A refusal that reaches dispatch is the whole failure mode B-7 names.
        """
        if str(determination) not in _DISPATCH_DETERMINATIONS:
            raise BillingRefusal(
                ErrorCode.CONFLICT,
                "Only an allow or escalate determination may dispatch an attempt.",
                details={"determination": str(determination)},
            )
        if self.status in _TERMINAL_ATTEMPT_STATUSES:
            raise BillingRefusal(
                ErrorCode.CONFLICT,
                "This attempt is terminal and cannot be dispatched.",
                details={"attempt_id": str(self.id), "status": self.status.value},
            )
        self.status = AttemptStatus.DISPATCHED
        self.record(
            AttemptDispatched(
                attempt_id=str(self.id),
                invoice_id=str(self.invoice_id),
                intent_id="",
            )
        )

    def mark_refused(self, reason: str) -> None:
        """Terminal refusal (B-7). Idempotent in effect, but never a path back to `PROPOSED`."""
        if self.status is AttemptStatus.SETTLED:
            raise BillingRefusal(
                ErrorCode.CONFLICT,
                "A settled attempt cannot be refused.",
                details={"attempt_id": str(self.id)},
            )
        if self.status is AttemptStatus.REFUSED:
            return
        self.status = AttemptStatus.REFUSED
        if self._invoice is not None:
            # B-7: a refusal is terminal and side-effect free, and the invoice becomes payable again
            # (B-1). Nothing is reserved on the refused path.
            self._invoice.status = InvoiceStatus.OUTSTANDING
            self._invoice._active_attempt = None
        self.record(
            AttemptRefused(
                attempt_id=str(self.id),
                invoice_id=str(self.invoice_id),
                reason_codes=(str(reason),) if reason else (),
            )
        )
