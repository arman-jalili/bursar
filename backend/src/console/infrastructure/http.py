"""HTTP adapters for the six upstream ports (frozen signatures, no transport yet).

Canonical: .pi/architecture/modules/console.md#ports-upstream-clients
Reference: docs/contracts/console-contract-freeze.md §2.9

Adapters inherit the ports so mypy fails a client whose surface drifts. They own transport only —
URL, timeout, auth header, JSON decode — never a field rename (CON-02) and never a verdict (CON-08).

`AuthorityHttpAdapter.submit_signature` is the only write-shaped method in this file, and it takes
bytes (CON-03/CON-04).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from src.console.application.ports import (
    ApprovalInboxPort,
    BillsPort,
    ConstitutionPort,
    DeterminationPort,
    EvidencePort,
    ReceiptPort,
)

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


class AuthorityHttpAdapter(ApprovalInboxPort, DeterminationPort):
    """Authority: approvals, signature passthrough, refusal reason codes."""

    def __init__(self, config: HttpAdapterConfig) -> None:
        self._config = config

    async def list_pending(self, owner_scope: str) -> tuple[Mapping[str, object], ...]:
        raise NotImplementedError("CON-01 — see module doc")

    async def submit_signature(
        self, approval_id: str, raw_body: bytes, content_type: str
    ) -> Mapping[str, object]:
        raise NotImplementedError("CON-03 — see module doc")

    async def reasons_for(self, intent_id: str) -> tuple[str, ...]:
        raise NotImplementedError("CON-07 — see module doc")


class BillingHttpAdapter(BillsPort):
    """Billing: invoice list and status. Reads only — there is no write method on the port (CON-04)."""

    def __init__(self, config: HttpAdapterConfig) -> None:
        self._config = config

    async def list_invoices(self, scope: str) -> tuple[Mapping[str, object], ...]:
        raise NotImplementedError("CON-01 — see module doc")

    async def get_invoice(self, invoice_id: str) -> Mapping[str, object]:
        raise NotImplementedError("CON-02 — see module doc")


class SettlementHttpAdapter(ReceiptPort):
    """Settlement: receipt lookup for the payer view."""

    def __init__(self, config: HttpAdapterConfig) -> None:
        self._config = config

    async def receipt_for(self, invoice_id: str) -> Mapping[str, object] | None:
        raise NotImplementedError("CON-06 — see module doc")


class EvidenceHttpAdapter(EvidencePort):
    """Evidence: envelopes and the verified/tampered verdict, proxied (CON-08)."""

    def __init__(self, config: HttpAdapterConfig) -> None:
        self._config = config

    async def list_envelopes(self, intent_id: str | None) -> tuple[Mapping[str, object], ...]:
        raise NotImplementedError("CON-01 — see module doc")

    async def verify(self, envelope_id: str) -> Mapping[str, object]:
        raise NotImplementedError("CON-08 — see module doc")


class MandateHttpAdapter(ConstitutionPort):
    """Mandate: constitution and payee list for display; the console may not publish either."""

    def __init__(self, config: HttpAdapterConfig) -> None:
        self._config = config

    async def current(self) -> Mapping[str, object]:
        raise NotImplementedError("CON-01 — see module doc")

    async def payees(self) -> tuple[Mapping[str, object], ...]:
        raise NotImplementedError("CON-01 — see module doc")
