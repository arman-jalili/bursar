"""Billing infrastructure — adapters for the frozen domain ports.

Canonical: docs/architecture/modules/billing.md#architecture
Reference: docs/contracts/billing-contract-freeze.md (Persistence contract)

What lives here, and nothing else:

    models.py        SQLAlchemy rows (`billing_invoices`, `billing_attempts`, `billing_outbox`)
    mappers.py       row ⇄ aggregate translation
    repositories.py  SQLAlchemy implementations of `domain/repositories.py` + the outbox writer

The storage mirrors of B-3 (`UNIQUE(invoice_hash)`) and B-1 (partial unique index on the active
attempt) are in `models.py` and in `migrations/versions/002_billing.py`, because a guarantee the
database does not enforce is a guarantee a concurrent request can forget.

No domain type is imported *by* this package's consumers; the arrows point inward.
"""
