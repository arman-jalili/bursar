"""PaymentAttempt — the agent's only legal output (frozen).

Canonical: .pi/architecture/modules/billing.md#components-paymentattempt
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
from dataclasses import dataclass

from src.billing.domain.ids import AttemptId, InvoiceId
from src.billing.domain.invoice import Invoice
from src.billing.domain.values import AttemptStatus
from src.shared.domain.aggregate import AggregateRoot

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


@dataclass(eq=False)
class PaymentAttempt(AggregateRoot):
    """The agent's structured proposal to pay one invoice. Carries no authority of its own."""

    id: AttemptId
    invoice_id: InvoiceId
    status: AttemptStatus

    @classmethod
    def from_proposal(cls, payload: Mapping[str, object], invoice: Invoice) -> PaymentAttempt:
        """Translate an untrusted proposal into an attempt in status `PROPOSED`.

        Raises:
            ProposalRejected: the payload carried a forbidden key (B-5).
            InvoiceAlreadySettled: the invoice is closed (B-2).
            InvoiceNotPayable: an attempt is already in flight (B-1).
            AmountMismatch: the proposed amount differs from the invoice amount (B-6).
        """
        raise NotImplementedError("B-5 — see module doc")

    def mark_dispatched(self, *, determination: str) -> None:
        """Move to `DISPATCHED` only for an allow/escalate determination (B-7).

        Raises:
            BillingRefusal: the determination is a refusal — the attempt must stay terminal, with no
                side effect. A refusal that reaches dispatch is the whole failure mode B-7 names.
        """
        raise NotImplementedError("B-7 — see module doc")

    def mark_refused(self, reason: str) -> None:
        """Terminal refusal (B-7). Idempotent in effect, but never a path back to `PROPOSED`."""
        raise NotImplementedError("B-7 — see module doc")
