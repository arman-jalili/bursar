"""Billing value objects and closed sets (frozen).

Canonical: .pi/architecture/modules/billing.md#components
Reference: docs/contracts/billing-contract-freeze.md (B-3, B-6)

    InvoiceHash    content hash of the invoice: duplicate key off-chain, nullifier seed on-chain (B-3)
    BilledAmount   positive USDC in integer micro-units (B-6)
    InvoiceStatus  closed set with terminal states (B-2)
    AttemptStatus  closed set with terminal states (B-1, B-7)

Both enumerations are closed and one-way: `SETTLED` and `REFUSED` are terminal. A status that could
reset is how a refused attempt becomes a payment (B-7).
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from src.shared.domain.value_object import ValueObject

__all__ = ["AttemptStatus", "BilledAmount", "InvoiceHash", "InvoiceStatus"]


@dataclass(frozen=True, slots=True)
class InvoiceHash(ValueObject):
    """Canonical content hash of an invoice document (B-3).

    Two invoices with the same hash **are the same invoice**. That single sentence is what makes a
    replayed bill fail before it consumes a cap slot, so the hash function must be deterministic across
    processes: canonical field order, no floats, no locale-dependent formatting.
    """

    value: str

    @classmethod
    def from_document(cls, document: Mapping[str, object]) -> InvoiceHash:
        """Deterministic hash over the normalized document. Raises on an empty/malformed document."""
        raise NotImplementedError("B-3 — see module doc")

    def same_as(self, other: InvoiceHash) -> bool:
        """True when both hashes identify the same bill (the duplicate test, B-3)."""
        raise NotImplementedError("B-3 — see module doc")


@dataclass(frozen=True, slots=True)
class BilledAmount(ValueObject):
    """A positive USDC amount in integer micro-units (B-6, ADR-002).

    A float would let an amount compare equal to the invoice while differing by a rounding error, which
    is exactly how a split attempt slips under a threshold.
    """

    micro_usdc: int

    @classmethod
    def from_usdc(cls, amount: str | Decimal) -> BilledAmount:
        """Parse '42.50' exactly; refuse floats, negatives, zero and excess precision."""
        raise NotImplementedError("B-6 — see module doc")

    def same_as(self, other: BilledAmount) -> bool:
        """Exact equality — used to prove an attempt did not edit the invoice amount (B-6)."""
        raise NotImplementedError("B-6 — see module doc")


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
