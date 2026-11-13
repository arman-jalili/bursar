"""Mandate interface layer — declared, intentionally empty at contract freeze.

Canonical: .pi/architecture/modules/mandate.md#api-endpoints
Reference: .pi/architecture/decisions/ADR-004-api-design.md

What lands here in the HTTP item:

    http/router.py    the concrete FastAPI router (issue rule: controllers are CONCRETE and get no
                      separate interface file), registered in `src/apps/shell.py:register_routers`
    http/schemas.py   request/response bodies, translated to the DTOs in
                      `src/mandate/application/dto.py` — the DTOs stay framework-free

The endpoint contract is already frozen in the module doc's API Endpoints table
(method, path, input, output, auth); this package is only its transport binding.
"""
