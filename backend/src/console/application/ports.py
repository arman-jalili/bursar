"""Upstream ports (frozen) — raw payloads in, raw payloads out.

Canonical: .pi/architecture/modules/console.md#ports-upstream-clients
Reference: docs/contracts/console-contract-freeze.md §2.5

Two rules are expressed by the signatures, not by convention:

1. **Ports return `Mapping[str, object]`, not typed DTOs.** Narrowing is the ACL's job (CON-01); a
   port that returned a typed model would put the whitelist behind whichever adapter built it, and
   a new upstream field would appear by editing an adapter instead of a whitelist.
2. **There is no write-shaped method other than `submit_signature`.** No `create_intent`, no
   `dispatch`, no `settle`: a console that cannot name the operation cannot call it (CON-04).

`submit_signature` takes `bytes`. Not a parsed model, not a dict — there is nothing for the console
to normalise, default or re-encode (CON-03).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

__all__ = [
    "ApprovalInboxPort",
    "BillsPort",
    "ConstitutionPort",
    "DeterminationPort",
    "EvidencePort",
    "ReceiptPort",
]


class ApprovalInboxPort(Protocol):
    """Authority: pending approvals and the signature passthrough (ADR-005)."""

    async def list_pending(self, owner_scope: str) -> tuple[Mapping[str, object], ...]:
        """Pending approvals for this owner scope, as Authority sends them (CON-01)."""
        raise NotImplementedError("CON-01 — see module doc")

    async def submit_signature(
        self, approval_id: str, raw_body: bytes, content_type: str
    ) -> Mapping[str, object]:
        """Forward the received body byte-for-byte; Authority decides (CON-03)."""
        raise NotImplementedError("CON-03 — see module doc")


class DeterminationPort(Protocol):
    """Authority: *why* a payment was refused (ADR-007, Lock 2 reason codes)."""

    async def reasons_for(self, intent_id: str) -> tuple[str, ...]:
        """The reason codes for one refusal — never a verdict computed here (CON-07)."""
        raise NotImplementedError("CON-07 — see module doc")


class BillsPort(Protocol):
    """Billing: invoice list and status for the payer view."""

    async def list_invoices(self, scope: str) -> tuple[Mapping[str, object], ...]:
        """Bills visible to this scope, as Billing sends them (CON-01)."""
        raise NotImplementedError("CON-01 — see module doc")

    async def get_invoice(self, invoice_id: str) -> Mapping[str, object]:
        """One bill, unmodified — the exact fields come from the whitelist (CON-02)."""
        raise NotImplementedError("CON-02 — see module doc")


class ReceiptPort(Protocol):
    """Settlement: tx hash and settled time for the payer view."""

    async def receipt_for(self, invoice_id: str) -> Mapping[str, object] | None:
        """The settlement receipt, or None when the bill has not settled (CON-06)."""
        raise NotImplementedError("CON-06 — see module doc")


class EvidencePort(Protocol):
    """Evidence: envelope list and verification result (open-host)."""

    async def list_envelopes(self, intent_id: str | None) -> tuple[Mapping[str, object], ...]:
        """Envelopes for an intent, or all recent ones when `intent_id` is None (CON-01)."""
        raise NotImplementedError("CON-01 — see module doc")

    async def verify(self, envelope_id: str) -> Mapping[str, object]:
        """Evidence's verdict — the console proxies it and never recomputes it (CON-08)."""
        raise NotImplementedError("CON-08 — see module doc")


class ConstitutionPort(Protocol):
    """Mandate: constitution version, cap, threshold and payees — display only."""

    async def current(self) -> Mapping[str, object]:
        """The in-force constitution for display (CON-01)."""
        raise NotImplementedError("CON-01 — see module doc")

    async def payees(self) -> tuple[Mapping[str, object], ...]:
        """Payees and their status for display; the console may not change either (CON-01)."""
        raise NotImplementedError("CON-01 — see module doc")
