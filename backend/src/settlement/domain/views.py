"""Settlement's read models — the anti-corruption views the factory is allowed to see (frozen).

Canonical: .pi/architecture/modules/settlement.md#aggregate-settlementorder
Reference: docs/contracts/settlement-contract-freeze.md §2.4

The module doc's factory signature is `order(intent: PaymentIntentView, network, determination:
DeterminationView)`. Those two view types are frozen here, and they exist for one reason:

* Settlement is **conformist** to Mandate and Authority (context map), but it does not need the whole
  `PaymentIntent` aggregate to build an order — and an aggregate would hand Settlement methods it must
  never call (`PaymentIntent.issue`, ledger reads). A view is the smallest thing that carries the frozen
  facts: the signed amount, the address Mandate validated, the invoice hash, and the household scope.
* `PaymentIntentView` adds two fields Authority's aggregate does not store — `invoice_hash` and
  `household_id`. The invoice hash is Billing's identity for the bill and is the nullifier seed (SC-5);
  the household id is the nullifier scope. Neither may be re-read at submit time (conformist read:
  frozen on the intent, copied here, immutable afterwards). Phase B assembles this view in the
  application layer from `PaymentIntent` + Billing's invoice hash + Mandate's household reference; the
  domain never reaches across a context to get them.
* `DeterminationView` carries the verdict plus the one bit the escalation path adds. The rule itself —
  allow, or escalate that became `ApprovalGranted` — is `permits_dispatch()` (SC-1), so every caller
  asks the same question instead of comparing verdict strings in three places.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.authority.domain.ids import IntentId
from src.authority.domain.values import DeterminationVerdict
from src.mandate.domain.values import BankDigest, PayeeAddress
from src.shared.domain.money import Money

__all__ = ["DeterminationView", "PaymentIntentView"]


@dataclass(frozen=True, slots=True)
class PaymentIntentView:
    """The frozen facts of one signed intent, as Settlement reads them (SC-1, SC-2, SC-9).

    Immutable by construction: `payee_address`, `amount`, `invoice_hash` and `household_id` are copied
    from the intent at order time and never re-read at submit time (S-2). The address is Mandate's
    `PayeeAddress` — never an invoice-supplied string.
    """

    intent_id: IntentId
    invoice_id: str
    payee_address: PayeeAddress
    #: The signed amount. Settlement never derives it from a document or a proposal (SC-9).
    amount: Money
    #: Billing's identity for the bill; the nullifier seed (SC-5).
    invoice_hash: str
    #: Mandate's household reference — the nullifier scope (SC-5). Never invoice text.
    household_id: str
    #: Mandate's verified digest, carried to `command_params` (SC-2).
    bank_digest: BankDigest
    is_new_payee: bool = False
    requires_owner_signature: bool = False


@dataclass(frozen=True, slots=True)
class DeterminationView:
    """Authority's verdict as read for this dispatch (SC-1).

    `approval_granted` is what turns an `escalate` into a permission. It is a separate bit rather than a
    fourth verdict because the verdict records what Authority decided and the approval records what the
    owner then did; collapsing them would lose the audit trail.
    """

    intent_id: IntentId
    verdict: DeterminationVerdict
    approval_granted: bool = False
    determination_id: str = ""

    def permits_dispatch(self) -> bool:
        """True only for `allow`, or for `escalate` with an approval already granted (SC-1).

        A `deny` is never a permission, and an `escalate` without the approval is not one either —
        which is exactly the state the escalation path must not be able to skip.
        """
        raise NotImplementedError("SC-1 — see module doc")
