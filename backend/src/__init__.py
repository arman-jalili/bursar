"""Bursar — delegated household bill-paying with a machine-enforced constitution.

Canonical: .pi/architecture/decisions/ADR-001-architecture-pattern.md
Reference: .pi/architecture/implementation-roadmap.md#phase-0-project-bootstrap-hours-01

Package layout (bounded contexts are created in their own build phase, never in Phase 0):

    src/shared/        shared kernel — domain primitives, config, logging, error envelope
    src/apps/          composition roots (deployables), one package per service
    src/mandate/       Phase 1 — household, payees, constitution
    src/billing/       Phase 2 — invoices, payment attempts
    src/authority/     Phase 3 — intents, determinations, cap ledger
    src/settlement/    Phase 4 — orders, nullifiers, receipts
    src/evidence/      Phase 5 — envelopes, anchors
    src/console/       Phase 6 — read models (adapter depth: no domain layer)
"""
