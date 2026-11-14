"""The engine-status surface: quotable data, no cache, and an honest "unreachable".

Canonical: .pi/architecture/modules/console.md#api-endpoints
Reference: docs/runbook-settlement.md (the Rigorix operating procedure)

Why these assertions and not others
-----------------------------------
A status endpoint is only worth having if a reviewer can trust the *absence* of a claim as much as
the claim. So the tests cover the three ways this could quietly lie:

1. it serves a cached "reachable: true" after the engine died  -> `Cache-Control: no-store`
2. an unreachable engine becomes a 500 (page dies) or a 200 with an empty body (page invents it)
   -> 200, `reachable: false`, and the error text names the failure
3. the authority deployable grows a second, unattended copy of the surface -> 404 there
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from src.shared.interfaces import engine as engine_module


@pytest.fixture
def console_client(console_client: TestClient) -> TestClient:
    return console_client


def test_it_passes_the_engines_own_version_fields_through(
    console_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The claim is the engine's, not ours: fields are copied verbatim, plus `raw` for diffing."""
    monkeypatch.setattr(
        engine_module,
        "read_engine_version",
        lambda base_url, timeout: {
            "name": "rigorix-server",
            "engine_version": "1.14.3",
            "api_version": "1.0.0",
            "anchor": {"head": "01a1bf02", "id": "anchor-1"},
            "history_integrity": "local_unanchored",
            "capabilities": ["jsonrpc-2.0"],
            "schemas": ["envelope.json"],
            "something_new": "kept only in raw",
        },
    )

    response = console_client.get("/v1/engine/status")

    assert response.status_code == 200
    body = response.json()
    assert body["reachable"] is True
    assert body["engine_version"] == "1.14.3"
    assert body["api_version"] == "1.0.0"
    assert body["anchor"] == {"head": "01a1bf02", "id": "anchor-1"}
    # Unknown fields are not dropped silently: `raw` is the engine's answer, so a reviewer can
    # diff what the page showed against what the engine said.
    assert body["raw"]["something_new"] == "kept only in raw"
    assert "latency_ms" in body


def test_it_is_never_cached(console_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A cached status is a status that can lie about a dead dependency."""
    monkeypatch.setattr(
        engine_module, "read_engine_version", lambda base_url, timeout: {"name": "rigorix-server"}
    )
    response = console_client.get("/v1/engine/status")
    assert response.headers["cache-control"] == "no-store"


def test_an_unreachable_engine_is_reported_not_raised(
    console_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The engine being down is a fact the strip must render, not a 500 that hides it."""

    def explode(base_url: str, timeout: float) -> dict[str, object]:
        raise ConnectionRefusedError("connection refused")

    monkeypatch.setattr(engine_module, "read_engine_version", explode)

    response = console_client.get("/v1/engine/status")

    assert response.status_code == 200
    body = response.json()
    assert body["reachable"] is False
    assert "ConnectionRefusedError" in body["error"]
    assert response.headers["cache-control"] == "no-store"


def test_the_authority_deployable_does_not_expose_it(authority_client: TestClient) -> None:
    """ADR-001: the authority service is not reachable from a page, so it must not host this."""
    assert authority_client.get("/v1/engine/status").status_code == 404