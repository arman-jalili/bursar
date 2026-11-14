"""Settlement refusal vocabulary (frozen).

Canonical: .pi/architecture/modules/settlement.md#components
Reference: docs/contracts/settlement-contract-freeze.md §3

Every refusal extends the shared `RefusalError`, so:

* the API layer needs **no Settlement-specific exception handling** — a refusal is a documented error
  with a domain code everywhere in this context (ADR-004);
* a test can assert `pytest.raises(RefusalError)` and still be specific about the cause;
* a refusal never becomes a `500`. A revert, a duplicate, or a missing authority is the product working.

Each class exists because one invariant needs it named:

    DispatchWithoutAuthority       SC-1   no allow/approved determination behind the order
    SecondTransactionRefused       SC-3   a submitted order may never get a second hash
    OrderAlreadyConcluded          SC-4   an order concludes exactly once
    DuplicateSettlementBlocked     SC-5   the invoice's nullifier is already spent locally
    SettlementNotFinal             SC-7   a receipt cannot conclude a settlement before finality
    AmountIntegrityViolation       SC-9   the amount handed to the chain differs from the signed amount
    ReceiptCostMissing             SC-10  a receipt without gas/fee would make the ledger unaccountable
    UnknownNetwork                 SC-11  an unconfigured chain id (a default would leak an address)

Two status choices are deliberate and part of the contract:

* **409** for every state conflict (`DispatchWithoutAuthority`, `SecondTransactionRefused`,
  `OrderAlreadyConcluded`, `DuplicateSettlementBlocked`, `SettlementNotFinal`,
  `AmountIntegrityViolation`).
* **422** for `ReceiptCostMissing` and `UnknownNetwork`: both are *malformed data* (an adapter produced
  an incomplete receipt; configuration named a chain nobody configured), not a conflict with the
  order's state.

Payloads are passed as an explicit `details` mapping, never as a `**kwargs` tail: a splat can smuggle a
key named `retryable` or `code` into `RefusalError` and silently rewrite the refusal's semantics.
"""

from __future__ import annotations

from src.shared.domain.errors import ErrorCode, RefusalError

__all__ = [
    "AmountIntegrityViolation",
    "DispatchWithoutAuthority",
    "DuplicateSettlementBlocked",
    "IllegalTransition",
    "OrderAlreadyConcluded",
    "ReceiptCostMissing",
    "SecondTransactionRefused",
    "SettlementNotFinal",
    "SettlementRefusal",
    "UnknownNetwork",
]


class SettlementRefusal(RefusalError):
    """Base for every refusal this context raises. Maps to HTTP 409 via the shared handler."""

    reason_code: str = "settlement_refused"


class DispatchWithoutAuthority(SettlementRefusal):
    """The determination does not permit dispatch, so no order may exist (SC-1)."""

    def __init__(self, verdict: str = "", intent_id: str = "") -> None:
        super().__init__(
            ErrorCode.CONFLICT,
            "This payment has no allowance to dispatch.",
            details={"verdict": verdict or "unknown", "intent_id": intent_id},
        )
        self.reason_code = "dispatch_without_authority"


class IllegalTransition(SettlementRefusal):
    """A state machine transition that must be unrepresentable was attempted (SC-3, SC-6, SC-8)."""

    def __init__(self, status: str = "", attempted: str = "") -> None:
        super().__init__(
            ErrorCode.CONFLICT,
            "That transition is not legal for this order.",
            details={"status": status or "unknown", "attempted": attempted or "unknown"},
        )
        self.reason_code = "illegal_transition"


class SecondTransactionRefused(SettlementRefusal):
    """A second tx hash is a second payment; the first hash is kept forever (SC-3)."""

    def __init__(self, order_id: str = "", existing_tx_hash: str = "") -> None:
        super().__init__(
            ErrorCode.CONFLICT,
            "This order already has a transaction hash; it will not be re-signed.",
            details={"order_id": order_id, "existing_tx_hash": existing_tx_hash},
        )
        self.reason_code = "second_transaction_refused"


class OrderAlreadyConcluded(SettlementRefusal):
    """A confirmed, reverted or abandoned order cannot be concluded again (SC-4)."""

    def __init__(self, order_id: str = "", status: str = "") -> None:
        super().__init__(
            ErrorCode.CONFLICT,
            "This order is already concluded; a settlement happens once.",
            details={"order_id": order_id, "status": status},
        )
        self.reason_code = "order_already_concluded"


class DuplicateSettlementBlocked(SettlementRefusal):
    """The invoice's nullifier was already spent, locally or on-chain (SC-5, scenario 6).

    `409`, not Billing's `DUPLICATE_INVOICE`: that code belongs to the *record a bill* path. Here the
    refusal is a conflict with a spent marker, and the console/evidence route on
    `reason_code = duplicate_settlement`.
    """

    def __init__(self, nullifier: str = "", order_id: str = "") -> None:
        super().__init__(
            ErrorCode.CONFLICT,
            "This invoice has already been settled; the nullifier is spent.",
            details={"nullifier": nullifier, "order_id": order_id},
        )
        self.reason_code = "duplicate_settlement"


class SettlementNotFinal(SettlementRefusal):
    """Fewer confirmations than the network requires: no cap commit yet (SC-7)."""

    def __init__(self, order_id: str = "", confirmations: int = 0, required: int = 0) -> None:
        super().__init__(
            ErrorCode.CONFLICT,
            "This settlement is not final yet.",
            details={
                "order_id": order_id,
                "confirmations": str(confirmations),
                "required": str(required),
            },
        )
        self.reason_code = "settlement_not_final"


class AmountIntegrityViolation(SettlementRefusal):
    """The amount about to be signed differs from the amount the intent was signed for (SC-9)."""

    def __init__(self, signed_micro_usdc: str = "", submitted_micro_usdc: str = "") -> None:
        super().__init__(
            ErrorCode.AMOUNT_MISMATCH,
            "The submitted amount does not match the signed intent amount.",
            details={
                "signed_micro_usdc": signed_micro_usdc,
                "submitted_micro_usdc": submitted_micro_usdc,
            },
        )
        self.reason_code = "amount_integrity_violation"


class ReceiptCostMissing(SettlementRefusal):
    """A receipt without gas/fee cannot be accounted for, so it is not a receipt (SC-10).

    `422`: the chain adapter produced an incomplete fact. Accepting it would make `CostSummary`
    under-report spend, which is the one thing ADR-006 says the summary must never do.
    """

    def __init__(self, field: str = "") -> None:
        super().__init__(
            ErrorCode.VALIDATION_FAILED,
            "A chain receipt must record gas, gas price and a fee estimate.",
            details={"missing_field": field or "unknown"},
        )
        self.reason_code = "receipt_cost_missing"
        self.http_status = 422


class UnknownNetwork(SettlementRefusal):
    """No configuration exists for that chain id, and there is no default (SC-11)."""

    def __init__(self, chain_id: int = 0) -> None:
        super().__init__(
            ErrorCode.VALIDATION_FAILED,
            "That chain id has no settlement configuration.",
            details={"chain_id": str(chain_id)},
        )
        self.reason_code = "unknown_network"
        self.http_status = 422
