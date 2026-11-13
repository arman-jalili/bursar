"""Mandate DTOs — frozen request/result schemas (contract v1, AC #3).

Canonical: .pi/architecture/modules/mandate.md#application-services
Reference: .pi/architecture/decisions/ADR-004-api-design.md

Decisions encoded here:

* **USDC amounts travel as integer micro-units**, matching `Money`/`Cap` (ADR-002). A DTO that
  accepted `float` would put the rounding bug back at the edge.
* **Digests travel as hex strings, routing details never do.** The raw account number exists only
  inside `BankDigest.from_routing_details` — see `BankDigest`.
* **Commands are frozen** so a handler cannot mutate a request halfway through, and so a command can
  be logged and replayed.
* Every result exposes `events` as **event names plus ids**, not event objects: the HTTP layer must
  not gain the ability to mutate a domain event, and Evidence seals the real ones from the outbox.
* Results carry `version` for optimistic concurrency (ADR-002) and the ids the console will link to.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "ConstitutionVersionView",
    "CreateMandateCommand",
    "CreateMandateResult",
    "EligibilityView",
    "FreezePayeeCommand",
    "FreezePayeeResult",
    "PayeeView",
    "PublishConstitutionVersionCommand",
    "PublishConstitutionVersionResult",
    "ReapprovePayeeDigestCommand",
    "ReapprovePayeeDigestResult",
    "RegisterPayeeCommand",
    "RegisterPayeeResult",
    "ReviewPresentedDigestCommand",
    "ReviewPresentedDigestResult",
]


# ── shared views (read models returned by the application layer) ─────────────
@dataclass(frozen=True, slots=True)
class ConstitutionVersionView:
    """One constitution version as the API exposes it."""

    version: int
    cap_micro_usdc: int
    threshold_micro_usdc: int
    require_signature_for_new_payee: bool
    content_hash: str
    status: str
    published_at_iso: str = ""


@dataclass(frozen=True, slots=True)
class PayeeView:
    """A payee as the API exposes it. No routing details — only the digest (ADR-005)."""

    payee_id: str
    name: str
    address: str
    verified_digest: str
    status: str


@dataclass(frozen=True, slots=True)
class EligibilityView:
    """The dispatch-time verdict (FR-012). `reason` is a closed-set code, never prose."""

    verdict: str
    reason: str | None = None


# ── CreateMandate (FR-001) ──────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class CreateMandateCommand:
    """Owner establishes the household: parties + constitution v1 in one transaction."""

    owner_address: str
    owner_name: str
    payer_name: str
    agent_key_id: str
    cap_micro_usdc: int
    threshold_micro_usdc: int
    require_signature_for_new_payee: bool = True
    owner_proof: str = ""  # serialized EIP-712 signature; verified by the proofing adapter


@dataclass(frozen=True, slots=True)
class CreateMandateResult:
    household_id: str
    constitution_id: str
    owner_id: str
    payer_id: str
    agent_id: str
    version: int
    events: tuple[str, ...] = field(default_factory=tuple)


# ── PublishConstitutionVersion (FR-002) ─────────────────────────────────────
@dataclass(frozen=True, slots=True)
class PublishConstitutionVersionCommand:
    household_id: str
    cap_micro_usdc: int
    threshold_micro_usdc: int
    require_signature_for_new_payee: bool
    owner_proof: str = ""


@dataclass(frozen=True, slots=True)
class PublishConstitutionVersionResult:
    constitution_id: str
    version: ConstitutionVersionView
    events: tuple[str, ...] = field(default_factory=tuple)


# ── RegisterPayee (FR-004) ──────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class RegisterPayeeCommand:
    household_id: str
    name: str
    address: str
    #: Routing details are accepted once, hashed immediately, and never returned or stored raw.
    routing_scheme: str = ""
    routing_account_number: str = ""
    routing_number: str = ""
    owner_proof: str = ""


@dataclass(frozen=True, slots=True)
class RegisterPayeeResult:
    payee: PayeeView
    events: tuple[str, ...] = field(default_factory=tuple)


# ── QuarantinePayee (FR-005) — the scam path ────────────────────────────────
@dataclass(frozen=True, slots=True)
class ReviewPresentedDigestCommand:
    """An invoice presented routing details; compare them with the verified baseline.

    No owner proof: this path is triggered automatically by Billing, and its effect is to *reduce*
    authority (quarantine), never to grant it.
    """

    payee_id: str
    presented_digest: str
    invoice_id: str = ""


@dataclass(frozen=True, slots=True)
class ReviewPresentedDigestResult:
    payee: PayeeView
    quarantined: bool
    events: tuple[str, ...] = field(default_factory=tuple)


# ── ReapprovePayeeDigest (FR-005) ───────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class ReapprovePayeeDigestCommand:
    payee_id: str
    routing_scheme: str
    routing_account_number: str
    routing_number: str = ""
    owner_proof: str = ""


@dataclass(frozen=True, slots=True)
class ReapprovePayeeDigestResult:
    payee: PayeeView
    events: tuple[str, ...] = field(default_factory=tuple)


# ── FreezePayee (FR-006) ────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class FreezePayeeCommand:
    payee_id: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class FreezePayeeResult:
    payee: PayeeView
    events: tuple[str, ...] = field(default_factory=tuple)
