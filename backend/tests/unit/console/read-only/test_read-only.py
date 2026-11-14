"""CON-04 — the console cannot create an intent, attempt or settlement order.

Canonical: docs/architecture/modules/console.md#api-endpoints
Reference: docs/contracts/console-contract-freeze.md §1 (CON-04), §2.5, §2.12

The owner token is the strongest credential in the demo. If a console route reached a creating path,
that token would move money without Authority's determination or the mandate's rules. The route
table is the auth matrix's source of truth, so it is asserted through the router the app will serve.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.console.interfaces.api import CONSOLE_ROUTES, SIGNATURE_PATH, ConsoleDeps, build_router

CREATING_OPERATIONS = ("intent", "attempt", "settlement", "dispatch", "execute", "create")


@dataclass
class _NoProjection:
    """Builds nothing: the router is the only thing under test here."""


def _deps() -> ConsoleDeps:
    return ConsoleDeps(
        approval_inbox=_NoProjection(),  # type: ignore[arg-type]
        payer_bills=_NoProjection(),  # type: ignore[arg-type]
        evidence=_NoProjection(),  # type: ignore[arg-type]
    )


class TestReadOnly:
    def test_the_router_exposes_exactly_the_frozen_route_table(self) -> None:
        """CON-04: a route added outside the table bypasses the auth matrix."""
        router = build_router(_deps())
        routes = {(route.method, route.path) for route in router.routes}  # type: ignore[attr-defined]
        assert routes == {(route.method, route.path) for route in CONSOLE_ROUTES}

    def test_no_console_path_names_a_creating_operation(self) -> None:
        """CON-04: a path the console cannot name is an operation it cannot reach."""
        router = build_router(_deps())
        offending = [
            route.path
            for route in router.routes  # type: ignore[attr-defined]
            if any(operation in route.path.lower() for operation in CREATING_OPERATIONS)
        ]
        assert offending == []

    def test_no_console_route_mutates_besides_the_signature_passthrough(self) -> None:
        """CON-04: reads are GET; the one POST is the signature forward."""
        router = build_router(_deps())
        posts = [
            route.path
            for route in router.routes  # type: ignore[attr-defined]
            if "POST" in getattr(route, "methods", set())
        ]
        assert posts == [SIGNATURE_PATH]

    def test_the_owner_token_cannot_reach_a_bill_write(self) -> None:
        """CON-04: the payer surfaces are `console:read`; only the signature row carries a write."""
        router = build_router(_deps())
        assert {route.path for route in router.routes} == {  # type: ignore[attr-defined]
            route.path for route in CONSOLE_ROUTES
        }
        write_scopes = {route.scope for route in CONSOLE_ROUTES if route.mutating}
        assert write_scopes == {"authority:sign"}
        assert all(
            route.scope in ("authority:read", "authority:sign", "console:read", "evidence:read")
            for route in CONSOLE_ROUTES
        )
