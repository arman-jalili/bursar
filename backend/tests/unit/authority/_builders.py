"""Builders for the Authority suites (importable, not fixtures).

Canonical: docs/contracts/authority-contract-freeze.md
Reference: .pi/architecture/modules/authority.md#components

Importable rather than fixture-only because the contract-test directories are named after invariants
(`capledger-cap/`), and a hyphen cannot be a Python package — so a builder module is the only import path
that survives collection.

Every builder calls the frozen surface, so in Phase A it raises `NotImplementedError: A-n — see module
doc`. That is the intended red: the assertions are rules, and the red means the rule is not implemented.
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.authority.domain.ids import IntentId, new_id
from src.authority.domain.ports import AttemptView, ConstitutionView, InvoiceView, PayeeView
from src.authority.domain.values import Money
from src.mandate.domain.values import (
    BankDigest,
    Eligibility,
    EvmAddress,
    PayeeAddress,
    PayeeStatus,
    RoutingDetails,
)

OWNER_ADDRESS = EvmAddress("0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266")
PAYEE_ADDRESS = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
NOW = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)


def usdc(amount: str) -> Money:
    """Integer micro-units, parsed through the shared Money type (ADR-002)."""
    return Money.usdc(amount)


def a_digest(account: str = "DE89370400440532013000") -> BankDigest:
    return BankDigest.from_routing_details(
        RoutingDetails(scheme="sepa", account_number=account, routing_number="")
    )


def a_constitution(
    *, cap: str = "150", threshold: str = "25", version: int = 3
) -> ConstitutionView:
    return ConstitutionView(
        version=version,
        cap=usdc(cap),
        threshold=usdc(threshold),
        require_signature_for_new_payee=True,
        read_at=NOW,
    )


def a_payee(
    *, status: PayeeStatus = PayeeStatus.ELIGIBLE, account: str = "DE89370400440532013000"
) -> PayeeView:
    return PayeeView(
        payee_id="payee-1",
        address=PayeeAddress(PAYEE_ADDRESS),
        digest=a_digest(account),
        status=status,
        read_at=NOW,
    )


def an_invoice(*, amount: str = "42.50", payee_id: str = "payee-1") -> InvoiceView:
    return InvoiceView(invoice_id="inv-12", payee_id=payee_id, amount=usdc(amount))


def an_attempt(*, claimed: str | None = None) -> AttemptView:
    return AttemptView(
        attempt_id="attempt-7",
        invoice_id="inv-12",
        claimed_amount=usdc(claimed) if claimed else None,
    )


class StubMandateView:
    """A `MandateView` that answers from memory, and records how often it was asked.

    Records calls on purpose: A-6 says the decision re-reads, so a test can assert the port was consulted
    at decision time rather than at plan time.
    """

    def __init__(
        self,
        constitution: ConstitutionView | None = None,
        payee: PayeeView | None = None,
        eligibility: Eligibility | None = None,
    ) -> None:
        self._constitution = constitution or a_constitution()
        self._payee = payee or a_payee()
        self._eligibility = eligibility or Eligibility.allow()
        self.calls: list[tuple[str, str]] = []

    async def constitution_in_force(self, household_id: str) -> ConstitutionView:
        self.calls.append(("constitution_in_force", household_id))
        return self._constitution

    async def payee(self, payee_id: str) -> PayeeView:
        self.calls.append(("payee", payee_id))
        return self._payee

    async def eligibility(self, payee_id: str) -> Eligibility:
        self.calls.append(("eligibility", payee_id))
        return self._eligibility


def an_intent_id() -> IntentId:
    return IntentId(new_id())
