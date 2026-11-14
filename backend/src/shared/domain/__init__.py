"""Domain primitives shared by every bounded context.

Canonical: docs/architecture/decisions/ADR-001-architecture-pattern.md
Reference: docs/architecture/modules/mandate.md#components

This package is framework-free by construction (enforced by the domain-layer architecture
tests). If you need an import from
sqlalchemy or fastapi here, the design is wrong — put it in `infrastructure/` instead.
"""
