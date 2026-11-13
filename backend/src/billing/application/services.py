"""Billing application services — the two catalog names, frozen (FR-007, FR-009).

Canonical: .pi/architecture/modules/billing.md#application-services
Reference: docs/contracts/billing-contract-freeze.md §2.7

    RecordInvoice   FR-007   register a bill; B-3 duplicate guard, B-4 digest kept for comparison only
    ProposePayment  FR-009   translate an agent proposal; B-5 reject-not-sanitize, B-1, B-2, B-6

Names come from the exploration use-cases pass and are not negotiable: they are how the console, the
agent and the evidence trail refer to these use cases.

Each implementation must open exactly one `session_scope` and append the drained events to
`billing_outbox` in that same transaction (ADR-003). Nothing business-shaped lives here — the rules are
on the aggregates, which is why these classes have no logic even once Phase B lands.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.billing.application.dto import (
    ProposePaymentCommand,
    ProposePaymentResult,
    RecordInvoiceCommand,
    RecordInvoiceResult,
)

__all__ = ["ProposePayment", "RecordInvoice"]


class RecordInvoice(ABC):
    """Register an invoice: hash it, keep the presented digest, refuse a duplicate (FR-007)."""

    @abstractmethod
    async def execute(self, command: RecordInvoiceCommand) -> RecordInvoiceResult:
        """Record the bill.

        Raises:
            DuplicateInvoice: the document hash is already known (B-3).
            BillingRefusal: the presented digest could not be compared (B-4 delegation to Mandate).
        """
        raise NotImplementedError("B-3 — see module doc")


class ProposePayment(ABC):
    """Turn an agent proposal into a structured attempt — never into authority (FR-009)."""

    @abstractmethod
    async def execute(self, command: ProposePaymentCommand) -> ProposePaymentResult:
        """Create the attempt.

        Raises:
            ProposalRejected: the payload carried a forbidden key (B-5).
            InvoiceAlreadySettled: the invoice is closed (B-2).
            InvoiceNotPayable: an attempt is already in flight (B-1).
            AmountMismatch: the proposed amount differs from the invoice (B-6).
        """
        raise NotImplementedError("B-5 — see module doc")
