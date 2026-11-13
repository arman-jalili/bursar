"""Domain primitives shared by every bounded context.

Canonical: .pi/architecture/decisions/ADR-001-architecture-pattern.md
Reference: .pi/architecture/modules/mandate.md#components

This package is framework-free by construction (enforced by the `dip-domain` gate in
`.pi/scripts/languages/python/check_model_judgment.sh`). If you need an import from
sqlalchemy or fastapi here, the design is wrong — put it in `infrastructure/` instead.
"""
