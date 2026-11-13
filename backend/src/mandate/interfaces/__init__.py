"""Mandate interface layer — HTTP transport and scopes.

Canonical: .pi/architecture/modules/mandate.md#api-endpoints
Reference: .pi/architecture/decisions/ADR-004-api-design.md

The router is **concrete** (no interface file for controllers, per the epic's rules): there is exactly
one transport for this context, so an abstraction over it would be speculative. It is registered in
`src/apps/shell.py::register_routers`, which is the only place allowed to know about it.

The endpoint contract lives in the module doc's API Endpoints table; `http/schemas.py` is its typed
binding, and `http/deps.py` holds the ADR-005 scope checks.
"""
