"""Authority domain services — the two rules that cannot live on one aggregate (frozen).

Canonical: docs/architecture/modules/authority.md#domain-services
Reference: docs/contracts/authority-contract-freeze.md §2.10

`DeterminationPolicy` is a **stateless function-object**, not a god service. It is a domain service
because the verdict composes three things that live in three places: the constitution's threshold
and new-payee flag (Mandate), the payee's live eligibility (Mandate), and the ledger's headroom
(Authority). Putting it on `PaymentIntent` would drag two contexts into an immutable value.

`ApprovalBinder` exists because the EIP-712 **specification** is shared: the same field list must
generate the Python verifier and the Solidity checker (ADR-007). Keeping the typed-data document in
one place is what stops the two implementations from disagreeing about which bytes the owner signed.
Its *implementation* — the actual recovery — is an adapter concern; the interface is frozen here and
`Approval` still owns the binding rule (A-13 … A-15).

Neither service holds state, performs I/O, or raises on a refusal without a named reason. A body
without a reason is exactly what A-5 and A-7 forbid.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from src.authority.domain.cap_ledger import CapLedger
from src.authority.domain.determination import Determination
from src.authority.domain.payment_intent import PaymentIntent
from src.authority.domain.ports import ConstitutionView, PayeeView
from src.mandate.domain.values import EvmAddress

__all__ = ["ApprovalBinder", "DeterminationPolicy"]


class DeterminationPolicy(ABC):
    """Compose the rules into one verdict and say which rules fired (A-5 … A-8)."""

    @abstractmethod
    def decide(
        self,
        *,
        intent: PaymentIntent,
        constitution: ConstitutionView,
        payee: PayeeView,
        ledger: CapLedger,
        read_at: datetime,
        duplicate_invoice: bool = False,
    ) -> Determination:
        """Return `allow`, `deny` with at least one code, or `escalate`.

        All inputs come from the **same read** as the verdict (A-6): `constitution.read_at`,
        `payee.read_at` and `read_at` must agree, and `ledger` carries the snapshot the decision was
        taken against. A DENY names every rule that fired (A-5) and produces no reservation (A-8);
        only an `allow` may be followed by `CapLedger.try_reserve` (A-9).

        `duplicate_invoice` is Billing's fact, passed in rather than queried: the policy is pure,
        and a hidden read would make A-6 unverifiable.

        Raises:
            DeterminationWithoutReason: a deny was attempted without a `DenialReason`.
        """
        raise NotImplementedError("A-5 — see module doc")


class ApprovalBinder(ABC):
    """Own the EIP-712 typed-data document that binds a signature to one intent (A-13, A-15)."""

    @abstractmethod
    def typed_data(self, intent: PaymentIntent) -> Mapping[str, Any]:
        """The exact document the owner signs — fields from the intent, never from the caller.

        The mapping is the shared specification: the Python verifier and `PaymentRouter` must be
        generated from it, so a field added here is a field the contract checks (A-13). It must
        agree with `PaymentIntent.signed_payload()`; the two are asserted equal in the behaviour
        suite rather than maintained by hand.
        """
        raise NotImplementedError("A-13 — see module doc")

    @abstractmethod
    def recover_signer(self, *, typed_data_hash: str, signature_hex: str) -> EvmAddress:
        """Recover the address that produced the signature over that hash.

        Recovery answers *who signed*; comparing that address to the mandate owner is
        `Approval.verify` (A-15), and consuming the approval is `Approval.consume` (A-14). Keeping
        those three separate is deliberate: a binder that also granted authority would make the
        single-use rule impossible to test.
        """
        raise NotImplementedError("A-15 — see module doc")
