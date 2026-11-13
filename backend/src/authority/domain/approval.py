"""Approval and OwnerSignature — one signature, one intent, one use (frozen).

Canonical: .pi/architecture/modules/authority.md#components
Reference: docs/contracts/authority-contract-freeze.md (A-13 … A-15)

    A-13  binds intent_id + amount + payee_address + bank_digest; any mismatch invalidates it
    A-14  single-use and expiring; consuming it twice is impossible
    A-15  the recovered signer must equal the mandate owner

A-13 is what stops the 20 USDC approval from paying a 320 USDC bill elsewhere: the approval is bound to
*those bytes*, so it is invalid the moment any field changes. A single `typed_data_hash` is the binding
— comparing fields one by one is how a forgotten field becomes a hole.

A-14's expiry is not decoration: an approval with no window is an unlimited standing authority, which is
exactly what the mandate exists to prevent. `consume()` is one-way; there is no `reset()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.authority.domain.ids import ApprovalId, IntentId
from src.authority.domain.payment_intent import PaymentIntent
from src.mandate.domain.values import EvmAddress
from src.shared.domain.value_object import ValueObject

__all__ = ["Approval", "OwnerSignature"]


@dataclass(frozen=True, slots=True)
class OwnerSignature(ValueObject):
    """The EIP-712 signature bytes plus the recovered signer (A-15).

    A value object: it is a proof artifact with no lifecycle. Verifying it is the *Approval*'s job — the
    signature itself only carries what was signed and by whom.
    """

    signature_hex: str
    signer: EvmAddress

    def matches(self, intent: PaymentIntent, owner: EvmAddress) -> bool:
        """True when the signer is the mandate owner **and** the digest covers this intent (A-13, A-15)."""
        raise NotImplementedError("A-13 — see module doc")


@dataclass(eq=False)
class Approval:
    """A signature request bound to one intent, and the proof once granted (A-13 … A-15)."""

    id: ApprovalId
    intent_id: IntentId
    typed_data_hash: str
    expires_at: datetime
    consumed_at: datetime | None = None
    signature: OwnerSignature | None = None

    @classmethod
    def request(cls, intent: PaymentIntent, *, expires_at: datetime) -> Approval:
        """Open a signature request bound to this intent's exact fields (A-13)."""
        raise NotImplementedError("A-13 — see module doc")

    def verify(self, signature: OwnerSignature, *, owner: EvmAddress, now: datetime) -> None:
        """Accept the owner's signature, or refuse without changing state.

        Raises:
            ApprovalExpired: `now` is past `expires_at` (A-14).
            ApprovalBindingMismatch: the signature does not cover this intent, or was already consumed
                (A-13, A-14).
        """
        raise NotImplementedError("A-13 — see module doc")

    def consume(self, *, now: datetime) -> None:
        """Use the approval exactly once, before dispatch (A-14).

        Raises:
            ApprovalSingleUse: already consumed.
            ApprovalExpired: the window closed between signing and dispatch.
            ApprovalBindingMismatch: no verified signature to consume.
        """
        raise NotImplementedError("A-14 — see module doc")

    @property
    def is_usable(self) -> bool:
        """True when a signature is present, unconsumed and unexpired — the dispatch precondition."""
        raise NotImplementedError("A-14 — see module doc")
