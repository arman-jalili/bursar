"""Both deployables boot and answer health, with the error envelope intact.

Canonical: .pi/architecture/implementation-roadmap.md#phase-0-project-bootstrap-hours-01
Reference: .pi/architecture/decisions/ADR-004-api-design.md

Phase-0 acceptance: "Both services boot and answer /healthz and /readyz" — plus the two things that
are easy to get wrong in a skeleton: a 404 must still be the documented envelope (the console parses
it), and `/readyz` must tell the truth about what is not built yet.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("fixture", ["authority_client", "console_client"])
def test_healthz_is_alive(fixture: str, request: pytest.FixtureRequest) -> None:
    client = request.getfixturevalue(fixture)
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] in ("authority-service", "console-api")


@pytest.mark.parametrize("fixture", ["authority_client", "console_client"])
def test_readyz_checks_database_and_reports_build_state(
    fixture: str, request: pytest.FixtureRequest
) -> None:
    client = request.getfixturevalue(fixture)
    response = client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "ok"
    assert body["build"]["phase"] == 0
    assert body["build"]["wired_contexts"] == []
    assert body["build"]["pending_contexts"], "a skeleton must state what is missing"


def test_readyz_never_leaks_secrets(console_client: TestClient) -> None:
    body = console_client.get("/readyz").text
    assert "test-hmac-key-not-a-secret" not in body
    assert "test-rigorix-key" not in body
    assert "11" * 32 not in body
    assert '"hmac_key_set":true' in body.replace(" ", "")


def test_correlation_id_is_echoed(console_client: TestClient) -> None:
    response = console_client.get("/healthz", headers={"X-Request-Id": "req-abc"})
    assert response.headers["X-Request-Id"] == "req-abc"


def test_correlation_id_is_generated_when_absent(console_client: TestClient) -> None:
    response = console_client.get("/healthz")
    assert response.headers["X-Request-Id"]


def test_404_uses_the_error_envelope(console_client: TestClient) -> None:
    response = console_client.get("/v1/does-not-exist")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert error["retryable"] is False
    assert error["correlation_id"]


def test_refusal_maps_to_409_with_domain_code(console_client: TestClient) -> None:
    """A refusal is the product working, so it must not look like a server error."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.shared.domain.errors import ErrorCode, RefusalError
    from src.shared.interfaces.errors import install_error_handlers

    app = FastAPI()
    install_error_handlers(app)

    @app.get("/refuse")
    async def refuse() -> None:
        raise RefusalError(ErrorCode.PAYEE_FROZEN, "That payee is paused.", payee_id="p1")

    with TestClient(app) as client:
        response = client.get("/refuse")
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "PAYEE_FROZEN"
    assert error["details"] == {"payee_id": "p1"}
    assert error["retryable"] is False


def test_openapi_is_generated(console_client: TestClient) -> None:
    """The contract must exist from hour 1 — the React app builds against it (NFR-006)."""
    schema = console_client.get("/openapi.json").json()
    assert "/healthz" in schema["paths"]
    assert "/readyz" in schema["paths"]
    assert schema["info"]["title"].startswith("Bursar")


def test_authority_service_has_no_cors_but_console_does(
    authority_client: TestClient, console_client: TestClient
) -> None:
    """ADR-001: the enforcement lock must not be reachable from a browser page."""
    assert "access-control-allow-origin" not in {
        k.lower() for k in authority_client.options("/healthz").headers
    }
    preflight = console_client.options(
        "/healthz",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert preflight.headers.get("access-control-allow-origin") == "http://localhost:5173"
