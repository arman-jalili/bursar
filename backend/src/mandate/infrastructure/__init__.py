"""Mandate infrastructure layer — declared, intentionally empty at contract freeze.

Canonical: docs/architecture/decisions/ADR-002-data-storage-strategy.md
Reference: docs/architecture/modules/mandate.md#implementation-sequence (step 6)

What lands here in the persistence item:

    repositories.py   SQLAlchemy implementations of the domain-owned ports in
                      `src/mandate/domain/repositories.py` (ADR-008 `interface-ownership`)
    models.py         ORM tables, prefixed `mandate_`; never imported by `domain/`
    mappers.py        row -> aggregate translation, so ORM models stay out of the model

Deliberately empty now: a contract freeze that also writes adapters is not a freeze, and the
`interface-ownership` gate only checks adapters that exist.
"""
