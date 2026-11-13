"""Mandate value objects — immutable, equal by value, frozen contract v1.

Canonical: .pi/architecture/modules/mandate.md#value-objects-with-entity-vs-vo-justification
Reference: .pi/architecture/decisions/ADR-002-data-storage-strategy.md

Every type here is a value object, and the module doc argues why each one is *not* an entity:

    BankDigest    two equal digests ARE the same destination — there is no identity to track
    Cap           a "cap #7" distinct from a cap of 150 USDC is meaningless
    Threshold     same — a number whose meaning is positional inside a ConstitutionVersion
    PayeeStatus   a closed set of four states with defined transitions
    PartyRef      a (role, id) pair attributed in an event; carries no state of its own
    Eligibility   the derived verdict Authority consumes; pure data, no lifecycle
    EvmAddress / PayeeAddress / DisplayName / PayeeName   validated primitives

Every invariant a value object can carry is enforced in `__post_init__`: an invalid value must be
*unconstructible*, not merely rejected later, so no downstream check has to trust its input.
"""

from __future__ import annotations

import enum
import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal

from src.mandate.domain.errors import InvalidValue
from src.shared.domain.value_object import ValueObject

_EVM_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")

__all__ = [
    "BankDigest",
    "Cap",
    "DisplayName",
    "Eligibility",
    "EligibilityVerdict",
    "EvmAddress",
    "PartyRef",
    "PayeeAddress",
    "PayeeName",
    "PayeeStatus",
    "ReasonCode",
    "Role",
    "RoutingDetails",
    "Threshold",
]


class Role(enum.StrEnum):
    """The three parties of a mandate. Roles never overlap (H-1)."""

    OWNER = "owner"
    PAYER = "payer"
    AGENT = "agent"


@dataclass(frozen=True, slots=True)
class PartyRef(ValueObject):
    """Who acted, without embedding a whole party record.

    Frozen contract: `Role.AGENT` here is what makes `OwnerActionRequired` reachable (H-3).
    """

    role: Role
    id: str
    household_id: str = ""


@dataclass(frozen=True, slots=True)
class EvmAddress(ValueObject):
    """A 0x-prefixed 20-byte address (checksum case is preserved, not normalised)."""

    value: str

    def __post_init__(self) -> None:
        if not _EVM_ADDRESS.match(self.value):
            raise InvalidValue(f"not an EVM address: {self.value!r}")


@dataclass(frozen=True, slots=True)
class PayeeAddress(ValueObject):
    """The payout address of a payee — the only destination Settlement will ever encode.

    Distinct type from `EvmAddress` on purpose: the owner's address and a payee's address are not
    interchangeable, and the type system is the cheapest place to say so.
    """

    value: str

    def __post_init__(self) -> None:
        if not _EVM_ADDRESS.match(self.value):
            raise InvalidValue(f"not a payee address: {self.value!r}")


@dataclass(frozen=True, slots=True)
class DisplayName(ValueObject):
    """A human name for a party (owner or payer)."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise InvalidValue("display name cannot be blank")
        if len(self.value) > 120:
            raise InvalidValue("display name is too long (120 chars)")


@dataclass(frozen=True, slots=True)
class PayeeName(ValueObject):
    """A payee's name as the owner typed it; uniqueness is per household."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise InvalidValue("payee name cannot be blank")
        if len(self.value) > 120:
            raise InvalidValue("payee name is too long (120 chars)")


@dataclass(frozen=True, slots=True)
class RoutingDetails(ValueObject):
    """The bank routing fields a `BankDigest` is computed over.

    Kept as an explicit type so the digest function has one obvious input and no caller can hash a
    dict in a different field order.
    """

    scheme: str
    account_number: str
    routing_number: str = ""


@dataclass(frozen=True, slots=True)
class BankDigest(ValueObject):
    """Hash over payee routing details (P-2, P-5).

    The scam signal: an invoice presents a digest that does not match the verified one, so the
    payee is quarantined instead of the money being redirected.

    Frozen contract: `hash` is a hex string; `from_routing_details` is the only sanctioned way to
    compute one, so a caller cannot invent a digest format. `matches` compares digests, not
    routing details — the raw account number must never travel further than this type.
    """

    hash: str

    @classmethod
    def from_routing_details(cls, details: RoutingDetails) -> BankDigest:
        """Deterministic digest over the routing fields.

        Canonical JSON with sorted keys, then SHA-256, hex-encoded. Deterministic across runs and
        processes, and field order cannot matter: a one-character change in any field changes the
        digest, which is exactly the scam signal (AC #1).
        """
        canonical = json.dumps(
            {
                "scheme": details.scheme,
                "account_number": details.account_number,
                "routing_number": details.routing_number,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return cls(hash=hashlib.sha256(canonical).hexdigest())

    def matches(self, other: BankDigest) -> bool:
        """True when both digests describe the same destination (constant-time is unnecessary: not a secret)."""
        return self.hash == other.hash


@dataclass(frozen=True, slots=True)
class Cap(ValueObject):
    """The daily USDC ceiling, summed across all payees (H-6, A-9).

    `micro_usdc` is integer micro-units (ADR-002): a float would let a payment pass a cap check it
    should fail. A cap of zero or less would make every payment unpayable in a way that looks like a
    bug, so it cannot be constructed (AC #2).
    """

    micro_usdc: int

    def __post_init__(self) -> None:
        _require_micro_usdc(self.micro_usdc, "cap", allow_zero=False)

    def at_least(self, amount_micro: int) -> bool:
        """True when this cap can cover `amount_micro`."""
        _require_micro_usdc(amount_micro, "amount", allow_zero=True)
        return amount_micro <= self.micro_usdc


@dataclass(frozen=True, slots=True)
class Threshold(ValueObject):
    """Per-payment amount above which an owner signature is mandatory (H-6, A-4).

    Zero is legal (every payment escalates); negative is not.
    """

    micro_usdc: int

    def __post_init__(self) -> None:
        _require_micro_usdc(self.micro_usdc, "threshold", allow_zero=True)

    def exceeded_by(self, amount_micro: int) -> bool:
        """True when a payment of `amount_micro` must be escalated to the owner.

        Strictly greater: paying exactly the threshold does not escalate (the threshold is the
        auto-pay limit, so the limit itself is still automatic).
        """
        _require_micro_usdc(amount_micro, "amount", allow_zero=True)
        return amount_micro > self.micro_usdc


class PayeeStatus(enum.StrEnum):
    """Closed set of payee states (P-1…P-4). The transitions are the contract:

        NEW          ──▶ ELIGIBLE      after the first settled payment / owner pre-approval
        ELIGIBLE     ──▶ QUARANTINED   automatic, on a presented-digest mismatch
        QUARANTINED  ──▶ ELIGIBLE      only via an owner re-approval (P-3)
        any          ──▶ FROZEN        owner freeze; FROZEN never downgrades to QUARANTINED (P-4)

    `eligibility()` maps each state to a verdict; a state with no verdict is a bug, which is why
    the mapping is exhaustive rather than defaulted.
    """

    NEW = "new"
    ELIGIBLE = "eligible"
    QUARANTINED = "quarantined"
    FROZEN = "frozen"


class ReasonCode(enum.StrEnum):
    """Why a payment was refused or escalated — the *domain* vocabulary (lowercase).

    Distinct from `src.shared.domain.errors.ErrorCode`, which is the *wire* vocabulary (uppercase,
    ADR-004). Both are needed and neither may be derived from the other at runtime: the reason code
    is sealed into evidence and quoted by the console copy table, so it is a data value, not an
    HTTP detail. `tests/unit/mandate/domain-services/` asserts the two stay consistent —
    every non-escalation reason has a matching `ErrorCode` with the same meaning.

    Closed set: adding a code is a contract version bump (A-5 in the Authority module doc).
    """

    #: Escalate-only: a first-time payee is not an error, it just needs the owner (FR-014).
    NEW_PAYEE = "new_payee"

    #: Refusals — each maps to an `ErrorCode` of the same name in upper case.
    DIGEST_MISMATCH = "digest_mismatch"
    PAYEE_QUARANTINED = "payee_quarantined"
    PAYEE_FROZEN = "payee_frozen"
    CAP_EXCEEDED = "cap_exceeded"
    DUPLICATE_INVOICE = "duplicate_invoice"
    APPROVAL_INVALID = "approval_invalid"
    AMOUNT_MISMATCH = "amount_mismatch"
    BUDGET_EXHAUSTED = "budget_exhausted"

    @property
    def is_escalation(self) -> bool:
        """True for the codes that mean "ask the owner", not "no"."""
        return self is ReasonCode.NEW_PAYEE


class EligibilityVerdict(enum.StrEnum):
    """The three possible answers Authority may act on."""

    ALLOW = "allow"
    ESCALATE = "escalate"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class Eligibility(ValueObject):
    """The derived payability verdict, as consumed by Authority at dispatch (FR-012).

    A refusal carries a reason code from the closed set in `src/shared/domain/errors.py` so the
    console can explain it in household language and Evidence can seal it.
    """

    verdict: EligibilityVerdict
    reason: str | None = None

    def __post_init__(self) -> None:
        """An escalation or a denial without a reason is unusable: no console copy, no evidence code."""
        if self.verdict is not EligibilityVerdict.ALLOW and not self.reason:
            raise ValueError(f"Eligibility {self.verdict} requires a reason code")

    @classmethod
    def allow(cls) -> Eligibility:
        return cls(verdict=EligibilityVerdict.ALLOW)

    @classmethod
    def escalate(cls, reason: str) -> Eligibility:
        """Not refused, but not allowed without the owner: e.g. `new_payee` (FR-014)."""
        return cls(verdict=EligibilityVerdict.ESCALATE, reason=reason)

    @classmethod
    def deny(cls, reason: str) -> Eligibility:
        """Refused with a reason: `payee_quarantined` or `payee_frozen` (FR-018)."""
        return cls(verdict=EligibilityVerdict.DENY, reason=reason)

    @property
    def is_allowed(self) -> bool:
        return self.verdict is EligibilityVerdict.ALLOW

    @property
    def is_denied(self) -> bool:
        return self.verdict is EligibilityVerdict.DENY


def _require_micro_usdc(value: object, label: str, *, allow_zero: bool) -> None:
    """Shared guard: integer micro-units only (no float, no bool, no negative)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidValue(f"{label} must be integer micro-USDC, got {type(value).__name__}")
    if value < 0:
        raise InvalidValue(f"{label} cannot be negative: {value}")
    if value == 0 and not allow_zero:
        raise InvalidValue(f"{label} must be greater than zero")


def usdc_to_micro(amount: str | Decimal) -> int:
    """Parse a human USDC amount ('42.50') into integer micro-units, refusing excess precision."""
    if isinstance(amount, float):
        raise InvalidValue("refusing float USDC input; pass a str or Decimal")
    try:
        parsed = Decimal(amount)
    except (ArithmeticError, ValueError, TypeError) as exc:
        raise InvalidValue(f"not a USDC amount: {amount!r}") from exc
    micro = parsed * 1_000_000
    if micro != micro.to_integral_value():
        raise InvalidValue(f"USDC has 6 decimals; {amount!r} is too precise")
    return int(micro)
