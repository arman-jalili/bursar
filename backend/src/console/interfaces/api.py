"""The eight console endpoints (frozen surface) — one write, seven reads.

Canonical: .pi/architecture/modules/console.md#api-endpoints
Reference: docs/contracts/console-contract-freeze.md §2.11-§2.12

`CONSOLE_ROUTES` is frozen data because it is the contract the React team and the auth matrix are
built against *before* the router exists. Exactly one row is `mutating=True`; `tests/unit/console/
read-only/` asserts that and the absence of creating paths (CON-04).

Handlers are concrete, not an interface (issue note): a `RouterPort` would abstract FastAPI for no
gain. They take `ConsoleDeps` so the router is the only place that knows the composition, and every
one of them raises until Phase B.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from src.console.application.dto import (
    ApprovalInboxItem,
    ConstitutionReadModel,
    EvidenceReadModel,
    PayeeReadModel,
    PaymentReadModel,
    SignatureOutcome,
    VerificationReadModel,
)
from src.console.application.services import (
    ProjectApprovalInbox,
    ProjectEvidence,
    ProjectPayerBills,
)

__all__ = [
    "CONSOLE_ROUTES",
    "SIGNATURE_PATH",
    "ConsoleDeps",
    "Route",
    "approval_inbox",
    "build_router",
    "constitution",
    "evidence_list",
    "payee_list",
    "payer_bill",
    "payer_bills",
    "submit_signature",
    "verify",
]


@dataclass(frozen=True, slots=True)
class Route:
    """One HTTP row: method, path, required scope, and whether it mutates (CON-04)."""

    method: str
    path: str
    scope: str
    mutating: bool = False
    handler: str = ""


#: The only path in the module that changes state (ADR-005).
SIGNATURE_PATH: Final[str] = "/v1/console/approvals/{id}/signature"

CONSOLE_ROUTES: Final[tuple[Route, ...]] = (
    Route("GET", "/v1/console/approvals", "authority:read", handler="approval_inbox"),
    Route(
        "POST",
        SIGNATURE_PATH,
        "authority:sign",
        mutating=True,
        handler="submit_signature",
    ),
    Route("GET", "/v1/console/bills", "console:read", handler="payer_bills"),
    Route("GET", "/v1/console/bills/{invoice_id}", "console:read", handler="payer_bill"),
    Route("GET", "/v1/console/payees", "console:read", handler="payee_list"),
    Route("GET", "/v1/console/constitution", "console:read", handler="constitution"),
    Route("GET", "/v1/console/evidence", "evidence:read", handler="evidence_list"),
    Route("GET", "/v1/console/evidence/{id}/verify", "console:read", handler="verify"),
)


@dataclass(frozen=True, slots=True)
class ConsoleDeps:
    """The three projections the router wires. No session, no repository, no adapter (CON-04)."""

    approval_inbox: ProjectApprovalInbox
    payer_bills: ProjectPayerBills
    evidence: ProjectEvidence


def build_router(deps: ConsoleDeps) -> object:
    """Build the FastAPI router from `CONSOLE_ROUTES`.

    Raises:
        ReadOnlyViolation: a route outside `CONSOLE_ROUTES` was asked for (CON-04).
    """
    raise NotImplementedError("CON-04 — see module doc")


async def approval_inbox(deps: ConsoleDeps, owner_scope: str) -> tuple[ApprovalInboxItem, ...]:
    """GET /v1/console/approvals — the owner's pending signature requests (CON-01)."""
    raise NotImplementedError("CON-01 — see module doc")


async def submit_signature(
    deps: ConsoleDeps,
    approval_id: str,
    *,
    raw_body: bytes,
    content_type: str,
    owner_scope: str,
) -> SignatureOutcome:
    """POST /v1/console/approvals/{id}/signature — forward, never rewrite (CON-03)."""
    raise NotImplementedError("CON-03 — see module doc")


async def payer_bills(deps: ConsoleDeps, scope: str) -> tuple[PaymentReadModel, ...]:
    """GET /v1/console/bills — household-language bills (CON-06)."""
    raise NotImplementedError("CON-06 — see module doc")


async def payer_bill(deps: ConsoleDeps, scope: str, invoice_id: str) -> PaymentReadModel:
    """GET /v1/console/bills/{invoice_id} — one bill for the payer detail screen (CON-06)."""
    raise NotImplementedError("CON-06 — see module doc")


async def payee_list(deps: ConsoleDeps, owner_scope: str) -> tuple[PayeeReadModel, ...]:
    """GET /v1/console/payees — display-only payee status (CON-01)."""
    raise NotImplementedError("CON-01 — see module doc")


async def constitution(deps: ConsoleDeps, owner_scope: str) -> ConstitutionReadModel:
    """GET /v1/console/constitution — display-only cap/threshold/version (CON-01)."""
    raise NotImplementedError("CON-01 — see module doc")


async def evidence_list(
    deps: ConsoleDeps, owner_scope: str, intent_id: str | None = None
) -> tuple[EvidenceReadModel, ...]:
    """GET /v1/console/evidence — envelope hashes and reason codes (CON-01)."""
    raise NotImplementedError("CON-01 — see module doc")


async def verify(deps: ConsoleDeps, owner_scope: str, envelope_id: str) -> VerificationReadModel:
    """GET /v1/console/evidence/{id}/verify — Evidence's verdict, proxied (CON-08)."""
    raise NotImplementedError("CON-08 — see module doc")
