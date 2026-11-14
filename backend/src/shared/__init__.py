"""Shared kernel: the only code every bounded context may import.

Canonical: docs/architecture/decisions/ADR-001-architecture-pattern.md
Reference: docs/architecture/implementation-roadmap.md#phase-0-project-bootstrap-hours-01

Rules (ADR-001):
    * `shared/domain/` is pure Python — no FastAPI, no SQLAlchemy, no HTTP.
    * A context may import from `shared`; `shared` may never import from a context.
    * Nothing here knows what a payment is. Money is a number, not a policy.
"""
