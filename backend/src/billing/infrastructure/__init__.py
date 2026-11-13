"""Billing infrastructure — adapters for the frozen domain ports (Phase B).

Canonical: .pi/architecture/modules/billing.md#architecture
Reference: docs/contracts/billing-contract-freeze.md §5

Empty on purpose in Phase A. A contract freeze that also writes persistence hides which guarantees
are still missing; the SQLAlchemy repositories, the `UNIQUE(hash)` invoice table, the partial unique
index on the active attempt and the fixture loader arrive with the persistence item.

What will live here, and nothing else:

    repository/     SQLAlchemy implementations of `domain/repositories.py`
    parser/         fixture-backed `InvoiceDocumentParser`
    adapters/       `DigestReviewPort` → Mandate HTTP adapter

No domain type is imported *by* this package's consumers; the arrows point inward.
"""
