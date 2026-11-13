"""Builders shared by the Settlement suites (importable, not fixtures).

Canonical: docs/contracts/settlement-contract-freeze.md
Reference: .pi/architecture/modules/settlement.md#components

Importable rather than fixtures-only because the contract-test directories are named after invariants
(`amount-integrity/`), and a hyphenated directory cannot be an importable package — `from ..conftest
import ...` would fail collection. Keeping the builders here makes the suites independent of that.

Everything here is a **factory call into the frozen surface**, plus plain construction of the frozen
value/view dataclasses (no bodies involved). In Phase A the aggregate methods raise, which is why the
suites are red: the assertions are rules (SC-n), and red means the rules are not implemented.
"""

from __future__ import annotations

from src.authority.domain.ids import IntentId
from src.authority.domain.values import DeterminationVerdict
from src.mandate.domain.values import BankDigest, PayeeAddress
from src.settlement.domain.chain_receipt import ChainReceipt
from src.settlement.domain.ids import OrderId, ReceiptId, new_id
from src.settlement.domain.values import ChainNetwork, ReceiptStatus
from src.settlement.domain.views import DeterminationView, PaymentIntentView
from src.shared.domain.money import Money

PAYEE_ADDRESS = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
ANVIL_CHAIN_ID = 31337
BASE_SEPOLIA_CHAIN_ID = 84532
ANVIL_ROUTER = "0x5FbDB2315678afecb367f032d93F642f64180aa3"
SEPOLIA_ROUTER = "0x7A1b9d3f8E2c4a5B6d0E1f23A4b5C6d7E8f90A1b"


def an_intent(**overrides: object) -> PaymentIntentView:
    """A signed intent's frozen facts (SC-1, SC-2, SC-9)."""
    fields: dict[str, object] = {
        "intent_id": IntentId(new_id()),
        "invoice_id": "inv-2026-0042",
        "payee_address": PayeeAddress(PAYEE_ADDRESS),
        "amount": Money(42_500_000),
        "invoice_hash": "ab" * 32,
        "household_id": "hh-1",
        "bank_digest": BankDigest("cd" * 32),
        "is_new_payee": False,
        "requires_owner_signature": False,
    }
    fields.update(overrides)
    return PaymentIntentView(**fields)  # type: ignore[arg-type]


def a_determination(
    verdict: DeterminationVerdict = DeterminationVerdict.ALLOW,
    *,
    approval_granted: bool = False,
    intent_id: IntentId | None = None,
) -> DeterminationView:
    """An Authority verdict for the intent (SC-1)."""
    return DeterminationView(
        intent_id=intent_id or IntentId(new_id()),
        verdict=verdict,
        approval_granted=approval_granted,
        determination_id=new_id(),
    )


def an_anvil_network(confirmations_required: int = 1) -> ChainNetwork:
    """The Anvil configuration, built field-by-field (the `anvil()` factory is SC-11 itself)."""
    return ChainNetwork(
        chain_id=ANVIL_CHAIN_ID,
        router_address=ANVIL_ROUTER,
        usdc_address="0x0165878A594ca255338adfa4d48449f69242Eb8F",
        confirmations_required=confirmations_required,
    )


def a_receipt(
    confirmations: int = 1,
    *,
    status: ReceiptStatus = ReceiptStatus.SUCCESS,
    order_id: OrderId | None = None,
    revert_reason: str = "",
    gas_used: int = 51_000,
    gas_price: str = "1000000000",
    fee_micro_usdc: int = 51,
) -> ChainReceipt:
    """A chain receipt with its cost (SC-7, SC-10).

    Construction is itself part of SC-10: `ChainReceipt.__post_init__` refuses a missing cost, so a
    receipt that exists is a receipt that can be accounted for.
    """
    return ChainReceipt(
        id=ReceiptId(new_id()),
        order_id=order_id or OrderId(new_id()),
        tx_hash="0x" + "ef" * 32,
        block_number=1_000_042,
        confirmations=confirmations,
        status=status,
        gas_used=gas_used,
        gas_price=gas_price,
        fee_usdc_estimate=Money(fee_micro_usdc),
        is_anchor=False,
        revert_reason=revert_reason,
    )
