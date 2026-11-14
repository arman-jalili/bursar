"""Shared builders for the Billing suites (importable, not fixtures).

Canonical: docs/contracts/billing-contract-freeze.md
Reference: docs/architecture/modules/billing.md#components

Importable rather than pytest-plugin-only because the contract-test directories are named after
invariants (`at-most-one-attempt/`), and a directory name with a hyphen cannot be an importable package —
so `from ..conftest import ...` would fail collection. Keeping the builders here makes the suites
independent of that detail.
"""

from __future__ import annotations

from datetime import date

from src.billing.domain.values import BilledAmount
from src.mandate.domain.values import BankDigest

PAYEE_ADDRESS = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"


def a_document(**overrides: object) -> dict[str, object]:
    """A normalised invoice document; the hash of this is the bill's identity (B-3)."""
    document: dict[str, object] = {
        "issuer": "Northwind Energy",
        "invoice_number": "INV-2026-0042",
        "amount_usdc": "42.50",
        "due_date": "2026-11-20",
    }
    document.update(overrides)
    return document


def a_digest(account: str = "DE89370400440532013000") -> BankDigest:
    """A payee bank digest built through the Mandate value object (the only sanctioned way)."""
    from src.mandate.domain.values import RoutingDetails

    return BankDigest.from_routing_details(
        RoutingDetails(scheme="sepa", account_number=account, routing_number="")
    )


def an_amount(usdc: str = "42.50") -> BilledAmount:
    return BilledAmount.from_usdc(usdc)


def a_due_date() -> date:
    return date(2026, 11, 20)
