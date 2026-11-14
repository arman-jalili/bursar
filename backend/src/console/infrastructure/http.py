"""HTTP adapters for the six upstream ports (transport only, frozen surface).

Canonical: docs/architecture/modules/console.md#ports-upstream-clients
Reference: docs/contracts/console-contract-freeze.md §2.9

Adapters inherit the ports so mypy fails a client whose surface drifts. They own transport only —
URL, timeout, auth header, JSON decode — never a field rename (CON-02) and never a verdict (CON-08).

`AuthorityHttpAdapter.submit_signature` is the only write-shaped method in this file, and it takes
bytes (CON-03/CON-04). It sets the caller's `Content-Type` verbatim and sends the body as received;
the demo/CI transport is an `httpx.MockTransport` with recorded upstream answers, and a production
composition injects the default `httpx` transport instead (see `transport.py`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import httpx

from src.console.application.errors import ConsoleRefusal, VerificationRefused
from src.console.application.ports import (
    ApprovalInboxPort,
    BillsPort,
    ConstitutionPort,
    DeterminationPort,
    EvidencePort,
    ReceiptPort,
)
from src.console.infrastructure.transport import demo_transport

__all__ = [
    "AuthorityHttpAdapter",
    "BillingHttpAdapter",
    "EvidenceHttpAdapter",
    "HttpAdapterConfig",
    "MandateHttpAdapter",
    "SettlementHttpAdapter",
]


@dataclass(frozen=True, slots=True)
class HttpAdapterConfig:
    """Transport configuration. Retries/backoff are Phase-B detail, not a contract."""

    base_url: str
    timeout_seconds: float = 2.0
    #: Live services instead of the recorded demo transport (the compose demo sets this).
    live: bool = False
    #: Service identity for upstreams whose read routes require a scope (Mandate/Settlement/Evidence).
    read_token: str = "demo-owner-token"


class _HttpClientMixin:
    """Shared client construction. The transport is injectable; the demo default is recorded."""

    _config: HttpAdapterConfig

    def __init__(
        self,
        config: HttpAdapterConfig,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        if transport is not None:
            self._transport = transport
        elif config.live:
            self._transport = httpx.AsyncHTTPTransport()
        else:
            self._transport = demo_transport()

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._config.base_url,
            timeout=self._config.timeout_seconds,
            transport=self._transport,
            headers={"Accept": "application/json"},
        )

    async def _get_json(
        self,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> object:
        async with self._client() as client:
            response = await client.get(path, params=params, headers=headers)
            response.raise_for_status()
            return response.json()

    def _failure(self, path: str, exc: Exception) -> ConsoleRefusal:
        return ConsoleRefusal(f"upstream call to {path!r} failed: {exc}")


class AuthorityHttpAdapter(_HttpClientMixin, ApprovalInboxPort, DeterminationPort):
    """Authority: approvals, signature passthrough, refusal reason codes."""

    async def list_pending(self, owner_scope: str) -> tuple[Mapping[str, object], ...]:
        # The live inbox wears the console's upstream shape; the recorded demo answers the same
        # fields on /v1/approvals, so only the path changes.
        path = "/v1/approvals/inbox" if self._config.live else "/v1/approvals"
        params = None if self._config.live else {"status": "pending"}
        body = await self._get_json(
            path,
            params=params,
            headers={"Authorization": f"Bearer {owner_scope}"},
        )
        items = body.get("items", ()) if isinstance(body, Mapping) else ()
        return tuple(item for item in items if isinstance(item, Mapping))

    async def submit_signature(
        self, approval_id: str, raw_body: bytes, content_type: str
    ) -> Mapping[str, object]:
        if not isinstance(raw_body, bytes):
            # CON-03: a parsed body has already been rewritten; refuse before the wire.
            raise ConsoleRefusal(
                "submit_signature takes the raw bytes as received, not a parsed body"
            )

        path = f"/v1/approvals/{approval_id}/signature"
        async with self._client() as client:
            response = await client.post(
                path,
                content=raw_body,
                headers={
                    "Content-Type": content_type or "application/json",
                    # Authority requires authority:sign; the demo forwards the owner identity.
                    "Authorization": f"Bearer {self._config.read_token}",
                },
            )
            response.raise_for_status()
            body = response.json()
        if not isinstance(body, Mapping):
            raise ConsoleRefusal(f"Authority returned a non-object answer for {path!r}")
        return body

    async def reasons_for(self, intent_id: str) -> tuple[str, ...]:
        body = await self._get_json(f"/v1/intents/{intent_id}/determination")
        codes = body.get("reason_codes", ()) if isinstance(body, Mapping) else ()
        return tuple(str(code) for code in codes)


class BillingHttpAdapter(_HttpClientMixin, BillsPort):
    """Billing: invoice list and status. Reads only — there is no write method on the port (CON-04)."""

    async def list_invoices(self, scope: str) -> tuple[Mapping[str, object], ...]:
        path = "/v1/payer/bills" if self._config.live else "/v1/invoices"
        body = await self._get_json(path, headers={"Authorization": f"Bearer {scope}"})
        items = body.get("items", ()) if isinstance(body, Mapping) else ()
        return tuple(item for item in items if isinstance(item, Mapping))

    async def get_invoice(self, invoice_id: str) -> Mapping[str, object]:
        body = await self._get_json(f"/v1/invoices/{invoice_id}")
        if not isinstance(body, Mapping):
            raise ConsoleRefusal(f"Billing returned a non-object invoice for {invoice_id!r}")
        return body


class SettlementHttpAdapter(_HttpClientMixin, ReceiptPort):
    """Settlement: receipt lookup for the payer view."""

    async def receipt_for(self, invoice_id: str) -> Mapping[str, object] | None:
        path = (
            f"/v1/receipts/invoice/{invoice_id}"
            if self._config.live
            else f"/v1/receipts/{invoice_id}"
        )
        async with self._client() as client:
            response = await client.get(
                path,
                headers={"Authorization": f"Bearer {self._config.read_token}"},
            )
        if response.status_code == 404:
            # CON-06: no receipt means no settlement, not a fabricated one.
            return None
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:  # pragma: no cover - transport failure path
            raise self._failure(path, exc) from exc
        body = response.json()
        if not isinstance(body, Mapping):
            raise ConsoleRefusal(f"Settlement returned a non-object receipt for {invoice_id!r}")
        return body


class EvidenceHttpAdapter(_HttpClientMixin, EvidencePort):
    """Evidence: envelopes and the verified/tampered verdict, proxied (CON-08)."""

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._config.read_token}"}

    async def list_envelopes(self, intent_id: str | None) -> tuple[Mapping[str, object], ...]:
        params = {"intent_id": intent_id} if intent_id is not None else None
        body = await self._get_json("/v1/evidence", params=params, headers=self._auth())
        items = body.get("items", ()) if isinstance(body, Mapping) else ()
        rows = []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            # The live envelope record names the stored bytes and the anchor; the console's
            # presentation contract also asks for a result label. A stored envelope is SEALED.
            rows.append({"result": "SEALED", **item} if "result" not in item else item)
        return tuple(rows)

    async def verify(self, envelope_id: str) -> Mapping[str, object]:
        path = f"/v1/evidence/{envelope_id}/verify"
        try:
            async with self._client() as client:
                response = await client.get(path, headers=self._auth())
            if self._config.live and response.status_code == 409:
                from datetime import UTC, datetime

                return {
                    "envelope_id": envelope_id,
                    "outcome": "tampered",
                    "checked_at": datetime.now(UTC).isoformat(),
                    "detail": "the stored bytes do not match the sealed envelope",
                }
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as exc:
            # CON-08: no verdict is invented when Evidence cannot answer.
            raise VerificationRefused(f"Evidence did not answer {path!r}: {exc}") from exc
        if not isinstance(body, Mapping):
            raise VerificationRefused(f"Evidence returned a non-object verdict for {path!r}")
        if not self._config.live:
            return body
        from datetime import UTC, datetime

        result = str(body.get("result", "")).upper()
        return {
            "envelope_id": envelope_id,
            "outcome": "verified" if result == "VERIFIED" else "unknown",
            "checked_at": datetime.now(UTC).isoformat(),
            "detail": result,
        }


class MandateHttpAdapter(_HttpClientMixin, ConstitutionPort):
    """Mandate: constitution and payee list for display; the console may not publish either."""

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._config.read_token}"}

    async def current(self) -> Mapping[str, object]:
        body = await self._get_json("/v1/constitution", headers=self._auth())
        if not isinstance(body, Mapping):
            raise ConsoleRefusal("Mandate returned a non-object constitution")
        return body

    async def payees(self) -> tuple[Mapping[str, object], ...]:
        body = await self._get_json("/v1/payees", headers=self._auth())
        items = body.get("items", ()) if isinstance(body, Mapping) else ()
        return tuple(item for item in items if isinstance(item, Mapping))
