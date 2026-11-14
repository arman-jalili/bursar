"""Mandate domain layer — aggregates, values, events, ports. Framework-free.

Canonical: docs/architecture/modules/mandate.md#components
Reference: docs/architecture/decisions/ADR-002-data-storage-strategy.md

Frozen contract v1 (2026-11-13). Everything public in this package is a promise to the other
contexts and to the implementation items:

    values.py       BankDigest · Cap · Threshold · PayeeStatus · PartyRef · Eligibility · ids
    errors.py       MandateError · OwnerActionRequired · OwnerProofInvalid · ThresholdExceedsCap
                    · ConstitutionCorrupted · PayeeNotEligible
    events.py       the 12 domain events of the context, frozen dataclasses
    entities.py     Owner · Payer · Agent (entities; identity persists)
    household.py    Household aggregate root (H-1…H-3)
    constitution.py Constitution · ConstitutionVersion (H-4…H-8)
    payee.py        Payee aggregate root (P-1…P-6)
    repositories.py HouseholdRepository · ConstitutionRepository · PayeeRepository (ABCs)
    ports.py        EligibilityResolver · OwnerSignatureProof

`domain/` imports no FastAPI, SQLAlchemy or httpx. Verified by the domain-layer architecture
tests and by
`tests/unit/mandate/repository-interfaces-owned-by-domain/`.
"""
