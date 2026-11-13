"""Settlement domain services — rules that belong to neither aggregate (frozen).

Canonical: .pi/architecture/modules/settlement.md#domain-services
Reference: docs/contracts/settlement-contract-freeze.md §2.6

    NullifierPolicy  derives keccak(invoice_hash, scope) and refuses a spent marker *before* any chain
                     call, so a local replay costs zero transactions (SC-5)
    FinalityPolicy   decides when a receipt is final for a network's required confirmations (SC-7)

Both are domain services because they need the nullifier/network value plus a rule, and neither belongs
on an aggregate: `SettlementOrder` already carries its nullifier, and `ChainReceipt` must not know a
network's confirmation policy.

`NullifierPolicy.guard_unspent` takes the answer as a boolean rather than a repository. The domain may
not perform I/O, and passing the *fact* keeps the refusal unit-testable without a database — the
repository still owns the unique constraint that makes the local lock real (SC-5).
"""

from __future__ import annotations

from src.settlement.domain.chain_receipt import ChainReceipt
from src.settlement.domain.values import ChainNetwork, Nullifier, SettlementStatus

__all__ = ["FinalityPolicy", "NullifierPolicy"]


class NullifierPolicy:
    """Derive the invoice's once-only marker and refuse a spent one (SC-5)."""

    def derive(self, invoice_hash: str, scope: str) -> Nullifier:
        """The canonical derivation used by both `SettlementOrder.order` and `SettleOnce` (SC-5).

        One derivation, two call sites: two formulae would eventually disagree, and a disagreement here
        is either a false duplicate refusal or a double payment.

        Raises:
            ValidationError: the invoice hash or scope is empty/malformed.
        """
        raise NotImplementedError("SC-5 — see module doc")

    def guard_unspent(self, nullifier: Nullifier, *, already_spent: bool) -> None:
        """Refuse locally when the nullifier is known spent (SC-5, scenario 6).

        Raises:
            DuplicateSettlementBlocked: the marker is spent; zero transactions may follow.
        """
        raise NotImplementedError("SC-5 — see module doc")


class FinalityPolicy:
    """Decide when a receipt has crossed the network's finality threshold (SC-7)."""

    def is_final(self, receipt: ChainReceipt, network: ChainNetwork) -> bool:
        """True only for a successful receipt at or beyond `network.confirmations_required` (SC-7)."""
        raise NotImplementedError("SC-7 — see module doc")

    def status_for(self, receipt: ChainReceipt, network: ChainNetwork) -> SettlementStatus:
        """Map a receipt to the order status it implies.

        `PENDING` below the threshold (no cap commit), `CONFIRMED` at/above it, `REVERTED` for a chain
        refusal — which is terminal and never retried (SC-6, SC-7).
        """
        raise NotImplementedError("SC-7 — see module doc")
