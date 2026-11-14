"""Row ⇄ domain translation for Authority.

Canonical: .pi/architecture/modules/authority.md#components
Reference: .pi/architecture/decisions/ADR-002-data-storage-strategy.md

Rehydration reconstructs value objects through their validation, so a corrupt row fails loudly at the
boundary rather than becoming a silent zero. Two details are deliberate:

* **A stored intent is rebuilt field-for-field.** It has no factory that accepts an existing id plus
  reads (by design — issuing is a decision), so rehydration constructs it directly and the immutable
  type guarantees nothing changed after load (A-1).
* **`Approval` rehydration never re-derives the typed-data hash.** The stored hash is what the owner
  signed; recomputing it from the intent at read time would make a tampered intent and a stale approval
  agree (A-13).
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime

from src.authority.domain.approval import Approval, OwnerSignature
from src.authority.domain.cap_ledger import CapLedger, Reservation, ReservationStatus
from src.authority.domain.determination import Determination
from src.authority.domain.ids import (
    ApprovalId,
    DeterminationId,
    IntentId,
    ReservationId,
)
from src.authority.domain.payment_intent import PaymentIntent
from src.authority.domain.values import DenialReason, DeterminationVerdict, Money
from src.authority.infrastructure.models import (
    ApprovalRow,
    CapLedgerRow,
    DeterminationRow,
    PaymentIntentRow,
    ReservationRow,
)
from src.mandate.domain.values import BankDigest, EvmAddress, PayeeAddress, PayeeStatus
from src.shared.domain.event import DomainEvent

__all__ = [
    "approval_to_domain",
    "approval_to_row",
    "determination_to_domain",
    "determination_to_row",
    "events_to_outbox",
    "intent_to_domain",
    "intent_to_row",
    "ledger_to_domain",
    "reservation_to_domain",
    "reservation_to_row",
]


# ── helpers ─────────────────────────────────────────────────────────────────
def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; the domain compares them to an aware `now`.

    Normalising at the boundary is what keeps `Approval.verify` a total function instead of a
    `TypeError` waiting for the first signature (A-14).
    """
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


# ── intent ──────────────────────────────────────────────────────────────────
def intent_to_domain(row: PaymentIntentRow) -> PaymentIntent:
    return PaymentIntent(
        id=IntentId(row.id),
        invoice_id=row.invoice_id,
        payee_id=row.payee_id,
        payee_address=PayeeAddress(row.payee_address),
        amount=Money(row.amount_micro_usdc),
        bank_digest=BankDigest(hash=row.bank_digest),
        is_new_payee=row.is_new_payee,
        requires_owner_signature=row.requires_owner_signature,
        constitution_version=row.constitution_version,
    )


def intent_to_row(intent: PaymentIntent) -> PaymentIntentRow:
    return PaymentIntentRow(
        id=intent.id,
        invoice_id=intent.invoice_id,
        payee_id=intent.payee_id,
        payee_address=intent.payee_address.value,
        amount_micro_usdc=intent.amount.micro_usdc,
        bank_digest=intent.bank_digest.hash,
        is_new_payee=intent.is_new_payee,
        requires_owner_signature=intent.requires_owner_signature,
        constitution_version=intent.constitution_version,
    )


# ── determination ───────────────────────────────────────────────────────────
def determination_to_domain(row: DeterminationRow) -> Determination:
    codes = tuple(DenialReason(code) for code in row.reason_codes.split(",") if code)
    return Determination(
        id=DeterminationId(row.id),
        intent_id=IntentId(row.intent_id),
        verdict=DeterminationVerdict(row.verdict),
        reason_codes=codes,
        constitution_version=row.constitution_version,
        payee_status_read=PayeeStatus(row.payee_status_read),
        read_at=_as_utc(row.read_at) or row.read_at,
        ledger_snapshot=Money(row.ledger_snapshot_micro_usdc),
    )


def determination_to_row(determination: Determination) -> DeterminationRow:
    return DeterminationRow(
        id=determination.id,
        intent_id=determination.intent_id,
        verdict=determination.verdict.value,
        reason_codes=",".join(code.value for code in determination.reason_codes),
        constitution_version=determination.constitution_version,
        payee_status_read=determination.payee_status_read.value,
        read_at=determination.read_at,
        ledger_snapshot_micro_usdc=determination.ledger_snapshot.micro_usdc,
    )


# ── ledger / reservation ────────────────────────────────────────────────────
def ledger_to_domain(row: CapLedgerRow) -> CapLedger:
    return CapLedger(
        day=row.day,
        cap=Money(row.cap_micro_usdc),
        committed=Money(row.committed_micro_usdc),
        reserved=Money(row.reserved_micro_usdc),
    )


def reservation_to_domain(row: ReservationRow) -> Reservation:
    return Reservation(
        id=ReservationId(row.id),
        intent_id=IntentId(row.intent_id),
        amount=Money(row.amount_micro_usdc),
        day=row.day,
        expires_at=_as_utc(row.expires_at) or row.expires_at,
        status=ReservationStatus(row.status),
    )


def reservation_to_row(reservation: Reservation) -> ReservationRow:
    return ReservationRow(
        id=reservation.id,
        intent_id=reservation.intent_id,
        amount_micro_usdc=reservation.amount.micro_usdc,
        day=reservation.day,
        expires_at=reservation.expires_at,
        status=reservation.status.value,
    )


# ── approval ────────────────────────────────────────────────────────────────
def approval_to_domain(row: ApprovalRow) -> Approval:
    signature: OwnerSignature | None = None
    if row.signature_hex is not None and row.signer is not None:
        signature = OwnerSignature(
            signature_hex=row.signature_hex,
            signer=EvmAddress(row.signer),
            signed_digest=row.signed_digest or "",
        )
    return Approval(
        id=ApprovalId(row.id),
        intent_id=IntentId(row.intent_id),
        typed_data_hash=row.typed_data_hash,
        expires_at=_as_utc(row.expires_at) or row.expires_at,
        consumed_at=_as_utc(row.consumed_at),
        signature=signature,
    )


def approval_to_row(approval: Approval) -> ApprovalRow:
    signature = approval.signature
    return ApprovalRow(
        id=approval.id,
        intent_id=approval.intent_id,
        typed_data_hash=approval.typed_data_hash,
        expires_at=approval.expires_at,
        consumed_at=approval.consumed_at,
        signature_hex=signature.signature_hex if signature else None,
        signer=signature.signer.value if signature else None,
        signed_digest=signature.signed_digest if signature else None,
    )


# ── outbox ──────────────────────────────────────────────────────────────────
def events_to_outbox(events: tuple[DomainEvent, ...]) -> list[dict[str, object]]:
    """Serialise drained events for `authority_outbox` (ADR-003).

    Timestamps become ISO-8601 strings so the sealed payload does not depend on the consumer's
    datetime library (the freeze requires `*_iso` fields).
    """
    rows: list[dict[str, object]] = []
    for event in events:
        payload: dict[str, object] = {}
        for field in dataclasses.fields(event):
            value = getattr(event, field.name)
            payload[field.name] = value.isoformat() if isinstance(value, datetime) else value
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
