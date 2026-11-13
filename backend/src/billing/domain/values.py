"""Billing value objects and closed sets (frozen).

Canonical: .pi/architecture/modules/billing.md#components
Reference: docs/contracts/billing-contract-freeze.md (B-3, B-6)

    InvoiceHash    content hash of the invoice: duplicate key off-chain, nullifier seed on-chain (B-3)
    BilledAmount   positive USDC in integer micro-units (B-6)
    InvoiceStatus  closed set with terminal states (B-2)
    AttemptStatus  closed set with terminal states (B-1, B-7)

Both enumerations are closed and one-way: `SETTLED` and `REFUSED` are terminal. A status that could
reset is how a refused attempt becomes a payment (B-7).

Implementation notes:

* `InvoiceHash` stores one digest per normalized document field rather than a single digest of the
  whole blob. The bill's identity is the tuple of field values, so a re-serialised document (dict order
  is not stable across producers) hashes identically while a one-character change to any field changes
  that field's digest. `same_as` compares the fields both documents declare, which lets a re-presented
  or partially re-encoded document be recognised as the same bill for B-3.
* `BilledAmount` parses `Decimal`, never `float`. A float is refused outright because `0.1 + 0.2`
  arithmetic is exactly how a split attempt makes an edited amount compare equal to the invoice.
"""

from __future__ import annotations

import enum
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from src.billing.domain.errors import BillingRefusal
from src.shared.domain.errors import ErrorCode
from src.shared.domain.value_object import ValueObject

__all__ = ["AttemptStatus", "BilledAmount", "InvoiceHash", "InvoiceStatus"]

#: Micro-units per USDC (ADR-002). Amounts are integers everywhere.
MICRO_UNITS_PER_USDC = 1_000_000

#: The most decimal places a USDC amount may carry. More precision is refused, not rounded.
USDC_DECIMALS = 6


def _require_decimal_string(amount: str | Decimal) -> Decimal:
    """Parse an amount to `Decimal`, refusing floats and non-finite values (B-6)."""
    if isinstance(amount, bool) or not isinstance(amount, (str, Decimal)):
        raise BillingRefusal(
            ErrorCode.VALIDATION_FAILED,
            "A USDC amount must be a decimal string or Decimal, never a float.",
            details={"amount_type": type(amount).__name__},
        )
    try:
        parsed = Decimal(amount)
    except (InvalidOperation, ValueError) as exc:
        raise BillingRefusal(
            ErrorCode.VALIDATION_FAILED,
            "A USDC amount must be a decimal number.",
            details={"amount": str(amount)},
        ) from exc
    if not parsed.is_finite():
        raise BillingRefusal(
            ErrorCode.VALIDATION_FAILED,
            "A USDC amount must be finite.",
            details={"amount": str(amount)},
        )
    return parsed


def _canonical_value(value: object) -> object:
    """Normalise one document value so two equivalent encodings serialize identically."""
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, Decimal)):
        return str(value)
    if value is None:
        return None
    return str(value)


def _field_digest(value: object) -> str:
    canonical = json.dumps(
        _canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class InvoiceHash(ValueObject):
    """Canonical content hash of an invoice document (B-3).

    Two invoices with the same hash **are the same invoice**. That single sentence is what makes a
    replayed bill fail before it consumes a cap slot, so the hash function must be deterministic across
    processes: canonical field order, no floats, no locale-dependent formatting.
    """

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise BillingRefusal(ErrorCode.VALIDATION_FAILED, "An invoice hash cannot be empty.")

    @classmethod
    def from_document(cls, document: Mapping[str, object]) -> InvoiceHash:
        """Deterministic hash over the normalized document. Raises on an empty/malformed document."""
        if not isinstance(document, Mapping) or not document:
            raise BillingRefusal(
                ErrorCode.VALIDATION_FAILED,
                "An invoice document cannot be empty.",
            )
        digests = {str(field): _field_digest(value) for field, value in document.items()}
        return cls(
            value=json.dumps(
                digests,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
        )

    def same_as(self, other: InvoiceHash) -> bool:
        """True when both hashes identify the same bill (the duplicate test, B-3).

        Documents are compared on the fields they both declare. Field *order* never matters (the
        canonical serialisation is sorted) and a re-presented document that omits a cosmetic field is
        still the same bill. Two documents with no field in common are different bills.
        """
        if not isinstance(other, InvoiceHash):
            return False
        try:
            mine = json.loads(self.value)
            theirs = json.loads(other.value)
        except (TypeError, ValueError):
            return self.value == other.value
        if not isinstance(mine, dict) or not isinstance(theirs, dict):
            return self.value == other.value
        shared = set(mine) & set(theirs)
        if not shared:
            return False
        return all(mine[field] == theirs[field] for field in shared)


@dataclass(frozen=True, slots=True)
class BilledAmount(ValueObject):
    """A positive USDC amount in integer micro-units (B-6, ADR-002).

    A float would let an amount compare equal to the invoice while differing by a rounding error, which
    is exactly how a split attempt slips under a threshold.
    """

    micro_usdc: int

    def __post_init__(self) -> None:
        if isinstance(self.micro_usdc, bool) or not isinstance(self.micro_usdc, int):
            raise BillingRefusal(
                ErrorCode.VALIDATION_FAILED,
                "A billed amount must be integer micro-USDC.",
                details={"micro_usdc": str(self.micro_usdc)},
            )
        if self.micro_usdc <= 0:
            raise BillingRefusal(
                ErrorCode.VALIDATION_FAILED,
                "A billed amount must be strictly positive.",
                details={"micro_usdc": str(self.micro_usdc)},
            )

    @classmethod
    def from_usdc(cls, amount: str | Decimal) -> BilledAmount:
        """Parse '42.50' exactly; refuse floats, negatives, zero and excess precision."""
        parsed = _require_decimal_string(amount)
        if parsed <= 0:
            raise BillingRefusal(
                ErrorCode.VALIDATION_FAILED,
                "A billed amount must be strictly positive.",
                details={"amount": str(amount)},
            )
        if -parsed.as_tuple().exponent > USDC_DECIMALS:  # type: ignore[operator]
            raise BillingRefusal(
                ErrorCode.VALIDATION_FAILED,
                f"A USDC amount may have at most {USDC_DECIMALS} decimal places.",
                details={"amount": str(amount)},
            )
        micro = parsed * MICRO_UNITS_PER_USDC
        if micro != micro.to_integral_value():
            raise BillingRefusal(
                ErrorCode.VALIDATION_FAILED,
                f"A USDC amount may have at most {USDC_DECIMALS} decimal places.",
                details={"amount": str(amount)},
            )
        return cls(micro_usdc=int(micro))

    def same_as(self, other: BilledAmount) -> bool:
        """Exact equality — used to prove an attempt did not edit the invoice amount (B-6)."""
        return isinstance(other, BilledAmount) and self.micro_usdc == other.micro_usdc


class InvoiceStatus(enum.StrEnum):
    """Invoice lifecycle. `SETTLED` is terminal (B-2); nothing transitions out of it."""

    RECEIVED = "received"
    OUTSTANDING = "outstanding"
    IN_FLIGHT = "in_flight"
    SETTLED = "settled"


class AttemptStatus(enum.StrEnum):
    """Attempt lifecycle. `SETTLED` and `REFUSED` are terminal (B-1, B-7).

    `REFUSED` is terminal on purpose: a refused attempt that could re-open would let an ignored refusal
    become a retry, which is the failure mode B-7 forbids.
    """

    PROPOSED = "proposed"
    ESCALATED = "escalated"
    APPROVED = "approved"
    DISPATCHED = "dispatched"
    SETTLED = "settled"
    REFUSED = "refused"
    EXPIRED = "expired"
