"""Fixtures shared by the Billing suites.

Canonical: docs/contracts/billing-contract-freeze.md
Reference: docs/architecture/modules/billing.md#components

Everything here is a **factory call into the frozen surface**. In Phase A those calls raise
`NotImplementedError`, which is why the suites are red: the assertions are rules (B-1…B-7), and the red
means the rules are not implemented yet — not that the tests are wrong.
"""

from __future__ import annotations

from datetime import date

import pytest
from src.billing.domain.ids import PayeeId, new_id
from src.billing.domain.values import BilledAmount
from src.mandate.domain.values import BankDigest

from tests.unit.billing._fixtures import a_digest, a_document


@pytest.fixture
def payee_id() -> PayeeId:
    return PayeeId(new_id())


@pytest.fixture
def amount() -> BilledAmount:
    return BilledAmount.from_usdc("42.50")


@pytest.fixture
def due_date() -> date:
    return date(2026, 11, 20)


@pytest.fixture
def presented_digest() -> BankDigest:
    return a_digest()


@pytest.fixture
def invoice(payee_id: PayeeId, amount: BilledAmount, due_date: date, presented_digest: BankDigest):
    """A recorded invoice — the starting point for every attempt rule (B-1, B-2, B-5, B-6)."""
    from src.billing.domain.invoice import Invoice

    return Invoice.from_document(
        payee_id=payee_id,
        amount=amount,
        due_date=due_date,
        document=a_document(),
        presented_digest=presented_digest,
    )


@pytest.fixture
def settled_invoice(invoice):
    """An invoice whose settlement is final (B-2)."""
    invoice.mark_settled()
    return invoice
