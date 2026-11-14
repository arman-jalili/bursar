"""The console's upstream transport seam — recorded demo fixtures, real HTTP elsewhere.

Canonical: docs/architecture/modules/console.md#ports-upstream-clients
Reference: docs/contracts/console-contract-freeze.md §2.9

The adapters in `http.py` own URL building, headers, status handling and JSON decode; the transport
owns delivery. That split is what lets CI exercise the adapters without a live Authority: the demo
deployable injects a recorded upstream (`demo_transport`) that answers the same paths the real
services do. A production composition injects `httpx.AsyncClient` with no custom transport.

Nothing here decides a field name or a verdict — the recorded answers are upstream shapes, and the
ACL narrows them exactly as it narrows a live response (CON-01, CON-02).
"""

from __future__ import annotations

from typing import Final

import httpx

__all__ = [
    "DEMO_APPROVALS",
    "DEMO_CONSTITUTION",
    "DEMO_ENVELOPES",
    "DEMO_INVOICES",
    "DEMO_PAYEES",
    "DEMO_RECEIPTS",
    "DEMO_VERDICTS",
    "demo_transport",
]

#: Recorded upstream payloads. Mixed-case addresses are the checksum and must stay mixed (CON-02).
DEMO_APPROVALS: Final[tuple[dict[str, object], ...]] = (
    {
        "approval_id": "ap-1",
        "intent_id": "intent-1",
        "invoice_id": "inv-1",
        "payee_name": "Northwind Insurance",
        "payee_address": "0x7A3fC2b1D4e5F60718293aBcDeF0123456789E9c2",
        "amount_usdc": "320.00",
        "bank_digest": "sha256:9f2ab7c1e0d4",
        "is_new_payee": True,
        "requires_owner_signature": True,
        "reason_codes": [],
        "expires_at": "2026-11-13T15:00:00Z",
        "typed_data_hash": "0x5c9d1b2f7a4e8c3d6b0a9f2e1c4d7b8a3e6f0c2d5a9b1e4f7c0d3a6b9e2f5c8d",
    },
)

DEMO_INVOICES: Final[tuple[dict[str, object], ...]] = (
    {
        "invoice_id": "inv-1",
        "payee_name": "Northwind Insurance",
        "payee_address": "0x7A3fC2b1D4e5F60718293aBcDeF0123456789E9c2",
        "amount_usdc": "320.00",
        "status": "SETTLED",
        "payout_simulated": True,
    },
    {
        "invoice_id": "inv-2",
        "payee_name": "Lakeside Water",
        "payee_address": "0x1B2c3D4e5F60718293aBcDeF0123456789E9c2A1b",
        "amount_usdc": "48.50",
        "status": "RECEIVED",
        "payout_simulated": False,
    },
)

DEMO_RECEIPTS: Final[dict[str, dict[str, object]]] = {
    "inv-1": {
        "invoice_id": "inv-1",
        "tx_hash": "0xabc123",
        "settled_at": "2026-11-13T14:02:00Z",
    }
}

DEMO_ENVELOPES: Final[tuple[dict[str, object], ...]] = (
    {
        "envelope_id": "env-1",
        "event_type": "PaymentIntentIssued",
        "occurred_at": "2026-11-13T13:55:00Z",
        "result": "SEALED",
        "anchor_tx": "0xanchor1",
    },
)

#: Recorded verdicts, including scenario 7's one-flipped-byte envelope. The outcome is Evidence's.
DEMO_VERDICTS: Final[dict[str, str]] = {
    "env-1": "tampered",
    "env-untouched": "verified",
}

DEMO_CONSTITUTION: Final[dict[str, object]] = {
    "version": "c-7",
    "cap_usdc": "500.00",
    "threshold_usdc": "100.00",
    "published_at": "2026-11-01T09:00:00Z",
}

DEMO_PAYEES: Final[tuple[dict[str, object], ...]] = (
    {"payee_id": "p-1", "display_name": "Northwind Insurance", "status": "ACTIVE"},
    {"payee_id": "p-2", "display_name": "Lakeside Water", "status": "PENDING"},
)


def _path(request: httpx.Request) -> str:
    return request.url.path.rstrip("/") or "/"


def _items(values: tuple[dict[str, object], ...]) -> httpx.Response:
    return httpx.Response(200, json={"items": [dict(value) for value in values]})


def _handler(request: httpx.Request) -> httpx.Response:
    """Answer the paths the adapters call, with the shapes the real services return."""
    path = _path(request)
    method = request.method.upper()

    if method == "GET" and path == "/v1/approvals":
        return _items(DEMO_APPROVALS)

    if method == "POST" and path.startswith("/v1/approvals/") and path.endswith("/signature"):
        # A passthrough always reaches here; the response is Authority's, not the console's.
        return httpx.Response(200, json={"granted": True, "reason_codes": []})

    if method == "GET" and path.startswith("/v1/intents/") and path.endswith("/determination"):
        return httpx.Response(200, json={"reason_codes": ["DIGEST_MISMATCH"]})

    if method == "GET" and path == "/v1/invoices":
        return _items(DEMO_INVOICES)

    if method == "GET" and path.startswith("/v1/invoices/"):
        invoice_id = path.rsplit("/", 1)[-1]
        for invoice in DEMO_INVOICES:
            if invoice["invoice_id"] == invoice_id:
                return httpx.Response(200, json=dict(invoice))
        return httpx.Response(404, json={"error": {"code": "NOT_FOUND"}})

    if method == "GET" and path.startswith("/v1/receipts/"):
        invoice_id = path.rsplit("/", 1)[-1]
        receipt = DEMO_RECEIPTS.get(invoice_id)
        if receipt is None:
            return httpx.Response(404, json={"error": {"code": "NOT_FOUND"}})
        return httpx.Response(200, json=dict(receipt))

    if method == "GET" and path == "/v1/evidence":
        return _items(DEMO_ENVELOPES)

    if method == "GET" and path.startswith("/v1/evidence/") and path.endswith("/verify"):
        envelope_id = path.split("/")[3]
        return httpx.Response(
            200,
            json={
                "envelope_id": envelope_id,
                "outcome": DEMO_VERDICTS.get(envelope_id, "unknown"),
                "checked_at": "2026-11-13T15:01:00Z",
            },
        )

    if method == "GET" and path == "/v1/constitution":
        return httpx.Response(200, json=dict(DEMO_CONSTITUTION))

    if method == "GET" and path == "/v1/payees":
        return _items(DEMO_PAYEES)

    return httpx.Response(404, json={"error": {"code": "NOT_FOUND"}})


def demo_transport() -> httpx.MockTransport:
    """The recorded upstream used by CI and the demo composition (no live service required)."""
    return httpx.MockTransport(_handler)
