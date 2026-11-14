"""Shared application layer: the unit-of-work boundary.

Canonical: docs/architecture/decisions/ADR-002-data-storage-strategy.md
Reference: docs/architecture/modules/authority.md#components

Why this package exists separately from `infrastructure/`: ADR-002 says *one application service
owns one transaction*, and ADR-008 enforces it with the `txn-placement` gate — no commit, rollback
or session handling may appear outside `application/`. A unit of work is therefore an application
concept, not an infrastructure detail. Keeping it here is what lets the gate stay strict instead of
accumulating exceptions.
"""
