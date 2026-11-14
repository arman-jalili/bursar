"""Row ⇄ aggregate translation — the seam that keeps ORM types out of the model.

Canonical: .pi/architecture/modules/settlement.md#repository-interfaces-owned-by-domain
Reference: docs/contracts/settlement-contract-freeze.md (SC-3, SC-5, SC-11)

Two rules, the same ones Billing and Mandate use:

1. **Rehydration is not a state change.** A stored order must not re-emit its creation events, so the
   mapper drains them after rebuilding the object. A restart that replayed `SettlementSubmitted` would
   make the outbox deliver a second fact for one transaction.
2. **Value objects are reconstructed through their validation** (`PayeeAddress`, `Nullifier`,
   `ChainNetwork`), so a corrupt row fails loudly at the boundary instead of becoming a silently
   different destination or a nullifier that never matches the chain.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime

from src.authority.domain.ids import IntentId
from src.mandate.domain.values import BankDigest, PayeeAddress
from src.settlement.domain.chain_receipt import ChainReceipt
from src.settlement.domain.ids import OrderId, ReceiptId
from src.settlement.domain.settlement_order import SettlementOrder
from src.settlement.domain.values import (
    ChainNetwork,
    Nullifier,
    ReceiptStatus,
    SettlementStatus,
)
from src.settlement.infrastructure.models import (
    SettlementOrderRow,
    SettlementReceiptRow,
)
from src.shared.domain.event import DomainEvent
from src.shared.domain.money import Money

__all__ = [
    "events_to_outbox",
    "order_to_domain",
    "order_to_row",
    "receipt_to_domain",
    "receipt_to_row",
]


def _settle(aggregate: object) -> None:
    """Rehydration is not a state change: drop the events the factory recorded."""
    pull = getattr(aggregate, "pull_events", None)
    if callable(pull):
        pull()


def order_to_domain(row: SettlementOrderRow) -> SettlementOrder:
    order = SettlementOrder(
        id=OrderId(row.id),
        intent_id=IntentId(row.intent_id),
        invoice_id=row.invoice_id,
        payee_address=PayeeAddress(row.payee_address),
        amount=Money(row.amount_micro_usdc),
        nullifier=Nullifier(row.nullifier),
        network=ChainNetwork(
            chain_id=row.chain_id,
            router_address=row.router_address,
            usdc_address=row.usdc_address,
            confirmations_required=row.confirmations_required,
        ),
        status=SettlementStatus(row.status),
        bank_digest=BankDigest(row.bank_digest),
        tx_hash=row.tx_hash,
        is_new_payee=row.is_new_payee,
        requires_owner_signature=row.requires_owner_signature,
        version=row.version,
    )
    _settle(order)
    return order


def order_to_row(order: SettlementOrder) -> SettlementOrderRow:
    return SettlementOrderRow(
        id=str(order.id),
        intent_id=str(order.intent_id),
        invoice_id=order.invoice_id,
        payee_address=order.payee_address.value,
        amount_micro_usdc=order.amount.micro_usdc,
        nullifier=order.nullifier.value,
        chain_id=order.network.chain_id,
        router_address=order.network.router_address,
        usdc_address=order.network.usdc_address,
        confirmations_required=order.network.confirmations_required,
        bank_digest=order.bank_digest.hash,
        is_new_payee=order.is_new_payee,
        requires_owner_signature=order.requires_owner_signature,
        status=order.status.value,
        tx_hash=order.tx_hash,
        version=order.version,
    )


def receipt_to_domain(row: SettlementReceiptRow) -> ChainReceipt:
    return ChainReceipt(
        id=ReceiptId(row.id),
        order_id=OrderId(row.order_id),
        tx_hash=row.tx_hash,
        block_number=row.block_number,
        confirmations=row.confirmations,
        status=ReceiptStatus(row.status),
        gas_used=row.gas_used,
        gas_price=row.gas_price,
        fee_usdc_estimate=Money(row.fee_micro_usdc),
        is_anchor=row.is_anchor,
        revert_reason=row.revert_reason,
    )


def receipt_to_row(receipt: ChainReceipt) -> SettlementReceiptRow:
    return SettlementReceiptRow(
        id=str(receipt.id),
        order_id=str(receipt.order_id),
        tx_hash=receipt.tx_hash,
        block_number=receipt.block_number,
        confirmations=receipt.confirmations,
        status=receipt.status.value,
        gas_used=receipt.gas_used,
        gas_price=receipt.gas_price,
        fee_micro_usdc=receipt.fee_usdc_estimate.micro_usdc,
        is_anchor=receipt.is_anchor,
        revert_reason=receipt.revert_reason,
        # Set here, not with `func.now()`: SQLite's server clock has second precision, and a re-poll
        # usually appends two receipts inside one second. Without microseconds "the latest receipt"
        # would be decided by a random uuid tie-break.
        observed_at=datetime.now(UTC).replace(tzinfo=None),
    )


def events_to_outbox(events: tuple[DomainEvent, ...]) -> list[dict[str, object]]:
    """Serialise drained events for `settlement_outbox` (ADR-003)."""
    rows: list[dict[str, object]] = []
    for event in events:
        payload = {f.name: getattr(event, f.name) for f in dataclasses.fields(event)}
        payload = {k: v.isoformat() if hasattr(v, "isoformat") else v for k, v in payload.items()}
        rows.append(
            {
                "event_id": event.event_id,
                "event_name": event.event_name,
                "aggregate_id": event.aggregate_id,
                "correlation_id": event.correlation_id,
                "payload": json.dumps(payload, sort_keys=True, default=str),
                "occurred_at": event.occurred_at,
            }
        )
    return rows
